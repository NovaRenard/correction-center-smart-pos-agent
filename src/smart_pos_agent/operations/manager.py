from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from ..config import Settings
from ..crm.commands import DeviceCheckCommand, PaymentStartCommand, RefundStartCommand
from ..crm.protocol import make_event
from ..events import StatusObserver, notify
from ..models import OperationRecord
from ..smart_pos.exceptions import SmartPosError, TerminalBusyError
from ..smart_pos.service import SmartPosService
from ..storage.operation_repository import OperationRepository
from .payment import normalize_reported_amount

logger = logging.getLogger(__name__)
EventSink = Callable[[dict[str, Any]], Awaitable[None]]


async def _discard_event(_: dict[str, Any]) -> None:
    return None


class OperationManager:
    """Durable, idempotent coordinator for the one physical terminal."""

    def __init__(
        self,
        settings: Settings,
        repository: OperationRepository,
        smart_pos: SmartPosService,
        event_sink: EventSink = _discard_event,
        status_observer: StatusObserver | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.smart_pos = smart_pos
        self.event_sink = event_sink
        self.status_observer = status_observer
        self._operation_lock = asyncio.Lock()

    def set_event_sink(self, event_sink: EventSink) -> None:
        self.event_sink = event_sink

    def active_operation_id(self) -> str | None:
        active = self.repository.get_active_operation()
        return active.crm_operation_id or active.id if active else None

    async def handle_device_check(self, command: DeviceCheckCommand) -> dict[str, Any]:
        existing = self.repository.get_command(command.command_id)
        if existing is not None:
            await self._emit(existing.response)
            return existing.response
        try:
            info, _ = await self.smart_pos.device_info(refresh=True)
            event = make_event(
                "device.status",
                {
                    "commandId": command.command_id,
                    "reachable": True,
                    "terminalId": info.terminal_id,
                    "serialNumber": info.serial_num,
                    "posNum": info.pos_num,
                    "activeOperationId": self.active_operation_id(),
                },
            )
        except (SmartPosError, ValueError) as exc:
            logger.warning("device_check_failed class=%s", exc.__class__.__name__)
            event = make_event(
                "device.status",
                {
                    "commandId": command.command_id,
                    "reachable": False,
                    "errorCode": "device_unavailable",
                },
            )
        self.repository.record_command(command.command_id, event)
        await self._emit(event)
        return event

    async def handle_payment(self, command: PaymentStartCommand) -> dict[str, Any]:
        return await self._handle_start(command, "payment")

    async def handle_refund(self, command: RefundStartCommand) -> dict[str, Any]:
        return await self._handle_start(command, "refund")

    async def _handle_start(
        self,
        command: PaymentStartCommand | RefundStartCommand,
        operation_type: Literal["payment", "refund"],
    ) -> dict[str, Any]:
        existing = self.repository.get_command(command.command_id)
        if existing is not None:
            event = self._known_state_event(existing.response, existing.operation_id)
            await self._emit(event)
            return event
        if self._operation_lock.locked() or self.repository.get_active_operation() is not None:
            return await self._reject_busy(command.command_id)
        async with self._operation_lock:
            existing = self.repository.get_command(command.command_id)
            if existing is not None:
                event = self._known_state_event(existing.response, existing.operation_id)
                await self._emit(event)
                return event
            active = self.repository.get_active_operation()
            if active is not None:
                return await self._reject_busy(command.command_id, active)
            operation = self._create_operation(command, operation_type)
            accepted = make_event(
                "command.accepted",
                {
                    "commandId": operation.command_id,
                    "operationId": operation.crm_operation_id,
                    "localOperationId": operation.id,
                    "operationType": operation.type,
                    "amount": operation.requested_amount,
                    "status": "accepted",
                },
            )
            # This write deliberately precedes a call to /payment or /refund.
            self.repository.record_command(operation.command_id, accepted, operation.id)
            await self._emit(accepted)
            try:
                return await self._start_and_poll(operation)
            except TerminalBusyError as exc:
                return await self._terminal_busy(operation, exc)
            except SmartPosError as exc:
                return await self._operation_error(operation, exc)
            except ValueError as exc:
                logger.error(
                    "operation_value_error class=%s",
                    exc.__class__.__name__,
                    extra={"operation_id": operation.id},
                )
                return await self._operation_error(operation, exc)

    def _create_operation(
        self, command: PaymentStartCommand | RefundStartCommand, operation_type: str
    ) -> OperationRecord:
        amount = command.payload.amount
        method: str | None = None
        transaction_id: str | None = None
        if isinstance(command, RefundStartCommand):
            method = command.payload.method
            transaction_id = command.payload.transaction_id
        return self.repository.create_operation(
            operation_id=str(uuid4()),
            crm_operation_id=command.operation_id,
            command_id=command.command_id,
            operation_type=operation_type,  # type: ignore[arg-type]
            amount=amount,
            method=method,
            transaction_id=transaction_id,
        )

    async def _start_and_poll(self, operation: OperationRecord) -> dict[str, Any]:
        if operation.type == "payment":
            start, raw = await self.smart_pos.payment(operation.requested_amount)
        else:
            if operation.requested_method is None or operation.requested_transaction_id is None:
                raise ValueError("Refund operation is missing method or transaction id")
            start, raw = await self.smart_pos.refund(
                operation.requested_amount,
                operation.requested_method,
                operation.requested_transaction_id,
            )
        operation = self.repository.update_operation(
            operation.id,
            process_id=start.process_id,
            status=start.status,
            sub_status=start.sub_status,
            response_json=raw,
        )
        started = make_event(
            f"{operation.type}.started",
            self._status_payload(operation, status=start.status, sub_status=start.sub_status),
        )
        await self._emit(started)
        return await self._poll(operation)

    async def _poll(self, operation: OperationRecord) -> dict[str, Any]:
        process_id = operation.process_id
        if not process_id:
            raise ValueError("Cannot poll operation without processId")
        terminal_id = operation.terminal_id
        if not terminal_id:
            info, _ = await self.smart_pos.device_info()
            terminal_id = info.terminal_id
            if not terminal_id:
                raise ValueError("Smart POS deviceinfo did not contain terminalId")
            operation = self.repository.update_operation(operation.id, terminal_id=terminal_id)
        unknown_since: float | None = None
        last_actualize = 0.0
        while True:
            result, raw = await self.smart_pos.status(process_id, terminal_id)
            operation = self.repository.update_operation(
                operation.id, status=result.status, sub_status=result.sub_status, response_json=raw
            )
            if result.status == "success":
                return await self._complete(operation, result, raw)
            if result.status == "fail":
                return await self._failed(operation, result, raw)
            await self._emit(
                make_event(
                    f"{operation.type}.status",
                    self._status_payload(
                        operation, status=result.status, sub_status=result.sub_status
                    ),
                )
            )
            if result.status == "unknown":
                now = time.monotonic()
                unknown_since = unknown_since or now
                if now - unknown_since >= self.settings.unknown_actualize_timeout_seconds:
                    return await self._manual_review(operation, raw)
                if now - last_actualize >= self.settings.actualize_interval_seconds:
                    actualized, actualized_raw = await self.smart_pos.actualize(process_id)
                    last_actualize = now
                    operation = self.repository.update_operation(
                        operation.id,
                        status=actualized.status,
                        sub_status=actualized.sub_status,
                        response_json=actualized_raw,
                    )
                    if actualized.status == "success":
                        return await self._complete(operation, actualized, actualized_raw)
                    if actualized.status == "fail":
                        return await self._failed(operation, actualized, actualized_raw)
                    if actualized.status != "unknown":
                        unknown_since = None
            else:
                unknown_since = None
            await asyncio.sleep(self.settings.status_poll_interval_seconds)

    async def resume_incomplete(self) -> None:
        """Resume persisted polling after a process restart; no new POS request is started."""
        for operation in self.repository.get_operations_without_process():
            # The request may have reached the terminal before a processId could be persisted.
            # Never replay it automatically, because that could double-charge a customer.
            logger.warning("operation_missing_process_id", extra={"operation_id": operation.id})
            await self._manual_review(operation, {})
        for operation in self.repository.get_incomplete_operations():
            if self._operation_lock.locked():
                return
            async with self._operation_lock:
                latest = self.repository.get_operation(operation.id)
                if latest is None or not latest.process_id:
                    continue
                logger.info("resuming_operation", extra={"operation_id": latest.id})
                try:
                    await self._poll(latest)
                except SmartPosError as exc:
                    await self._operation_error(latest, exc)
                except ValueError as exc:
                    logger.error(
                        "resume_value_error class=%s",
                        exc.__class__.__name__,
                        extra={"operation_id": latest.id},
                    )
                    await self._operation_error(latest, exc)

    async def _complete(
        self, operation: OperationRecord, result: Any, raw: dict[str, Any]
    ) -> dict[str, Any]:
        transaction_id = result.transaction_id or result.order_number or result.rrn
        method = result.method or operation.requested_method
        operation = self.repository.update_operation(
            operation.id,
            status="success",
            sub_status=result.sub_status,
            transaction_id=transaction_id,
            payment_method=method,
            terminal_id=result.terminal_id or operation.terminal_id,
            response_json=raw,
            completed_at=datetime.now(UTC),
        )
        payload = self._status_payload(operation, status="success", sub_status=result.sub_status)
        payload.update(
            {
                "amount": operation.requested_amount,
                "method": method,
                "transactionId": transaction_id,
                "orderNumber": result.order_number,
                "rrn": result.rrn,
                "terminalId": operation.terminal_id,
                "chequeInfo": result.cheque_info or {},
                "rawResponse": raw,
            }
        )
        reported_amount = normalize_reported_amount(result.cheque_info)
        if reported_amount is not None:
            payload["reportedAmount"] = reported_amount
        event = make_event(f"{operation.type}.completed", payload)
        self.repository.record_command(operation.command_id, event, operation.id)
        await self._emit(event)
        return event

    async def _failed(
        self, operation: OperationRecord, result: Any, raw: dict[str, Any]
    ) -> dict[str, Any]:
        operation = self.repository.update_operation(
            operation.id,
            status="fail",
            sub_status=result.sub_status,
            response_json=raw,
            completed_at=datetime.now(UTC),
        )
        event = make_event(
            f"{operation.type}.failed",
            {
                **self._status_payload(operation, status="fail", sub_status=result.sub_status),
                "errorCode": "terminal_failed",
                "rawResponse": raw,
            },
        )
        self.repository.record_command(operation.command_id, event, operation.id)
        await self._emit(event)
        return event

    async def _manual_review(
        self, operation: OperationRecord, raw: dict[str, Any]
    ) -> dict[str, Any]:
        operation = self.repository.update_operation(
            operation.id,
            status="manual_review",
            error_code="unknown_timeout",
            error_message="Smart POS could not determine the final result",
            response_json=raw,
            completed_at=datetime.now(UTC),
        )
        event = make_event(
            f"{operation.type}.manual_review",
            {
                **self._status_payload(
                    operation, status="unknown", sub_status=operation.sub_status
                ),
                "errorCode": "unknown_timeout",
                "rawResponse": raw,
            },
        )
        self.repository.record_command(operation.command_id, event, operation.id)
        await self._emit(event)
        return event

    async def _terminal_busy(
        self, operation: OperationRecord, exc: TerminalBusyError
    ) -> dict[str, Any]:
        self.repository.update_operation(
            operation.id,
            status="fail",
            error_code="terminal_busy",
            error_message=str(exc),
            completed_at=datetime.now(UTC),
        )
        event = make_event(
            "command.rejected",
            {
                "commandId": operation.command_id,
                "operationId": operation.crm_operation_id,
                "reason": "terminal_busy",
                "activeOperationId": self.active_operation_id(),
            },
        )
        self.repository.record_command(operation.command_id, event, operation.id)
        await self._emit(event)
        return event

    async def _operation_error(
        self, operation: OperationRecord, exc: SmartPosError | ValueError
    ) -> dict[str, Any]:
        logger.error(
            "operation_failed class=%s",
            exc.__class__.__name__,
            extra={"operation_id": operation.id},
        )
        operation = self.repository.update_operation(
            operation.id,
            status="fail",
            error_code="smart_pos_error",
            error_message=str(exc),
            completed_at=datetime.now(UTC),
        )
        event = make_event(
            f"{operation.type}.failed",
            {
                **self._status_payload(operation, status="fail", sub_status=operation.sub_status),
                "errorCode": "smart_pos_error",
            },
        )
        self.repository.record_command(operation.command_id, event, operation.id)
        await self._emit(event)
        return event

    async def _reject_busy(
        self, command_id: str, active: OperationRecord | None = None
    ) -> dict[str, Any]:
        active = active or self.repository.get_active_operation()
        event = make_event(
            "command.rejected",
            {
                "commandId": command_id,
                "reason": "terminal_busy",
                "activeOperationId": (active.crm_operation_id or active.id)
                if active
                else self.active_operation_id(),
            },
        )
        self.repository.record_command(command_id, event)
        await self._emit(event)
        return event

    def _known_state_event(
        self, stored_event: dict[str, Any], operation_id: str | None
    ) -> dict[str, Any]:
        if operation_id:
            operation = self.repository.get_operation(operation_id)
            if operation is not None:
                if operation.status == "success":
                    return stored_event
                return make_event(
                    f"{operation.type}.status",
                    self._status_payload(
                        operation, status=operation.status, sub_status=operation.sub_status
                    ),
                )
        return stored_event

    @staticmethod
    def _status_payload(
        operation: OperationRecord, *, status: str, sub_status: str | None
    ) -> dict[str, Any]:
        return {
            "commandId": operation.command_id,
            "operationId": operation.crm_operation_id,
            "processId": operation.process_id,
            "status": status,
            "subStatus": sub_status,
            "amount": operation.requested_amount,
        }

    async def _emit(self, event: dict[str, Any]) -> None:
        if event.get("type") == "device.status":
            payload = event.get("payload")
            if isinstance(payload, dict):
                notify(
                    self.status_observer,
                    "terminal.ready" if payload.get("reachable") else "terminal.unavailable",
                    payload,
                )
        notify(self.status_observer, "operation.event", event)
        await self.event_sink(event)
