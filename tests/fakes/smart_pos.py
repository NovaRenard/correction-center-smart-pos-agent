from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from smart_pos_agent.smart_pos.models import DeviceInfo, OperationResult, OperationStart


def result(status: str, sub_status: str | None = None, **extra: Any) -> OperationResult:
    return OperationResult(status=status, subStatus=sub_status, **extra)


class FakeSmartPos:
    def __init__(
        self,
        statuses: list[OperationResult] | None = None,
        actualized: list[OperationResult] | None = None,
    ) -> None:
        self.statuses = deque(
            statuses or [result("success", "QrTransactionSuccess", orderNumber="order-1")]
        )
        self.actualized = deque(actualized or [])
        self.payment_calls = 0
        self.refund_calls: list[tuple[int, str, str]] = []
        self.status_entered = asyncio.Event()
        self.status_release: asyncio.Event | None = None

    async def device_info(self, *, refresh: bool = False) -> tuple[DeviceInfo, dict[str, Any]]:
        info = DeviceInfo(posNum="pos-1", serialNum="serial-1", terminalId="terminal-1")
        return info, {"statusCode": 0, "data": info.model_dump(by_alias=True)}

    async def payment(
        self, amount: int, own_cheque: bool = False
    ) -> tuple[OperationStart, dict[str, Any]]:
        self.payment_calls += 1
        start = OperationStart(processId="process-payment", status="wait")
        return start, {"statusCode": 0, "data": start.model_dump(by_alias=True)}

    async def refund(
        self, amount: int, method: str, transaction_id: str, own_cheque: bool = False
    ) -> tuple[OperationStart, dict[str, Any]]:
        self.refund_calls.append((amount, method, transaction_id))
        start = OperationStart(processId="process-refund", status="wait")
        return start, {"statusCode": 0, "data": start.model_dump(by_alias=True)}

    async def status(
        self, process_id: str, terminal_id: str
    ) -> tuple[OperationResult, dict[str, Any]]:
        self.status_entered.set()
        if self.status_release is not None:
            await self.status_release.wait()
        value = self.statuses.popleft() if len(self.statuses) > 1 else self.statuses[0]
        return value, {"statusCode": 0, "data": value.model_dump(by_alias=True, exclude_none=True)}

    async def actualize(self, process_id: str) -> tuple[OperationResult, dict[str, Any]]:
        value = self.actualized.popleft() if len(self.actualized) > 1 else self.actualized[0]
        return value, {"statusCode": 0, "data": value.model_dump(by_alias=True, exclude_none=True)}
