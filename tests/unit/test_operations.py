from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import ValidationError

from smart_pos_agent.config import Settings
from smart_pos_agent.crm.commands import PaymentStartCommand, RefundPayload, RefundStartCommand
from smart_pos_agent.operations.manager import OperationManager
from smart_pos_agent.storage.operation_repository import OperationRepository
from tests.fakes.smart_pos import FakeSmartPos, result

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


def payment_command(command_id: str = "command-1") -> PaymentStartCommand:
    return PaymentStartCommand(
        type="payment.start",
        commandId=command_id,
        operationId="operation-1",
        payload={"amount": 10, "ownCheque": False},
    )


def refund_command(method: str = "qr") -> RefundStartCommand:
    return RefundStartCommand(
        type="refund.start",
        commandId=f"refund-{method}",
        operationId="operation-refund",
        payload={"amount": 10, "method": method, "transactionId": "tx-1"},
    )


def manager(
    settings: Settings,
    repository: OperationRepository,
    fake: FakeSmartPos,
    events: list[dict[str, Any]],
) -> OperationManager:
    async def append(event: dict[str, Any]) -> None:
        events.append(event)

    return OperationManager(settings, repository, fake, append)


@pytest.mark.asyncio
async def test_polling_wait_to_success(settings: Settings, repository: OperationRepository) -> None:
    fake = FakeSmartPos(
        [
            result("wait", "WaitUser"),
            result(
                "success",
                "QrTransactionSuccess",
                orderNumber="order-77",
                chequeInfo={"amount": "10"},
            ),
        ]
    )
    events: list[dict[str, Any]] = []
    outcome = await manager(settings, repository, fake, events).handle_payment(payment_command())
    assert outcome["type"] == "payment.completed"
    assert outcome["payload"]["transactionId"] == "order-77"
    assert outcome["payload"]["reportedAmount"] == 10
    assert any(event["type"] == "payment.status" for event in events)


@pytest.mark.asyncio
async def test_polling_wait_to_fail(settings: Settings, repository: OperationRepository) -> None:
    fake = FakeSmartPos([result("wait", "WaitUser"), result("fail", "QrTransactionFailure")])
    outcome = await manager(settings, repository, fake, []).handle_payment(payment_command())
    assert outcome["type"] == "payment.failed"
    assert outcome["payload"]["status"] == "fail"


@pytest.mark.asyncio
async def test_unknown_actualize_to_success(
    settings: Settings, repository: OperationRepository
) -> None:
    fake = FakeSmartPos(
        [result("unknown", "ProcessingCard")],
        [result("success", "CardTransactionSuccess", rrn="rrn-1", method="card")],
    )
    outcome = await manager(settings, repository, fake, []).handle_payment(payment_command())
    assert outcome["type"] == "payment.completed"
    assert outcome["payload"]["transactionId"] == "rrn-1"


@pytest.mark.asyncio
async def test_unknown_timeout_requires_manual_review(
    settings: Settings, repository: OperationRepository
) -> None:
    settings.unknown_actualize_timeout_seconds = 0.005
    fake = FakeSmartPos(
        [result("unknown", "ProcessingCard")], [result("unknown", "ProcessingCard")]
    )
    outcome = await manager(settings, repository, fake, []).handle_payment(payment_command())
    assert outcome["type"] == "payment.manual_review"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["qr", "card"])
async def test_qr_and_card_refund(
    settings: Settings, repository: OperationRepository, method: str
) -> None:
    fake = FakeSmartPos(
        [result("success", "ProcessRefund", transactionId="refund-tx", method=method)]
    )
    outcome = await manager(settings, repository, fake, []).handle_refund(refund_command(method))
    assert outcome["type"] == "refund.completed"
    assert fake.refund_calls == [(10, method, "tx-1")]


def test_rejects_invalid_refund_method() -> None:
    with pytest.raises(ValidationError):
        RefundPayload(amount=10, method="cash", transactionId="tx")


def test_rejects_negative_and_fractional_amounts() -> None:
    with pytest.raises(ValidationError):
        PaymentStartCommand(
            type="payment.start", commandId="n", operationId="o", payload={"amount": -1}
        )
    with pytest.raises(ValidationError):
        PaymentStartCommand(
            type="payment.start", commandId="f", operationId="o", payload={"amount": 10.5}
        )


@pytest.mark.asyncio
async def test_deduplicates_command_id(settings: Settings, repository: OperationRepository) -> None:
    fake = FakeSmartPos([result("success", "QrTransactionSuccess", orderNumber="tx")])
    operation_manager = manager(settings, repository, fake, [])
    first = await operation_manager.handle_payment(payment_command("same"))
    second = await operation_manager.handle_payment(payment_command("same"))
    assert first["type"] == "payment.completed"
    assert second["type"] == "payment.completed"
    assert fake.payment_calls == 1


@pytest.mark.asyncio
async def test_recovers_persisted_incomplete_operation(
    settings: Settings, repository: OperationRepository
) -> None:
    operation = repository.create_operation(
        operation_id="local-recovery",
        crm_operation_id="crm-recovery",
        command_id="cmd-recovery",
        operation_type="payment",
        amount=10,
        method=None,
        transaction_id=None,
    )
    repository.update_operation(
        operation.id,
        process_id="process-recovery",
        terminal_id="terminal-1",
        status="wait",
    )
    fake = FakeSmartPos([result("success", "QrTransactionSuccess", orderNumber="recovered")])
    operation_manager = manager(settings, repository, fake, [])
    await operation_manager.resume_incomplete()
    restored = repository.get_operation(operation.id)
    assert restored is not None
    assert restored.status == "success"


@pytest.mark.asyncio
async def test_restart_without_persisted_process_requires_manual_review(
    settings: Settings, repository: OperationRepository
) -> None:
    operation = repository.create_operation(
        operation_id="local-no-process",
        crm_operation_id="crm-no-process",
        command_id="cmd-no-process",
        operation_type="payment",
        amount=10,
        method=None,
        transaction_id=None,
    )
    await manager(settings, repository, FakeSmartPos(), []).resume_incomplete()
    restored = repository.get_operation(operation.id)
    assert restored is not None
    assert restored.status == "manual_review"


@pytest.mark.asyncio
async def test_rejects_second_parallel_operation(
    settings: Settings, repository: OperationRepository
) -> None:
    fake = FakeSmartPos([result("success", "QrTransactionSuccess", orderNumber="done")])
    fake.status_release = asyncio.Event()
    operation_manager = manager(settings, repository, fake, [])
    first_task = asyncio.create_task(operation_manager.handle_payment(payment_command("first")))
    await fake.status_entered.wait()
    second = await operation_manager.handle_payment(payment_command("second"))
    assert second["type"] == "command.rejected"
    assert second["payload"]["reason"] == "terminal_busy"
    fake.status_release.set()
    first = await first_task
    assert first["type"] == "payment.completed"
