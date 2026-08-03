from __future__ import annotations

from typing import Any

from .client import SmartPosClient
from .models import DeviceInfo, OperationResult, OperationStart


class SmartPosService:
    """Terminal-aware facade that supplies the terminal identifier to status requests."""

    def __init__(self, client: SmartPosClient) -> None:
        self.client = client
        self._device: DeviceInfo | None = None

    async def device_info(self, *, refresh: bool = False) -> tuple[DeviceInfo, dict[str, Any]]:
        if self._device is None or refresh:
            self._device, raw = await self.client.device_info()
            return self._device, raw
        return self._device, self._device.model_dump(by_alias=True, exclude_none=True)

    async def payment(
        self, amount: int, own_cheque: bool = False
    ) -> tuple[OperationStart, dict[str, Any]]:
        return await self.client.start_payment(amount, own_cheque)

    async def refund(
        self, amount: int, method: str, transaction_id: str, own_cheque: bool = False
    ) -> tuple[OperationStart, dict[str, Any]]:
        return await self.client.start_refund(amount, method, transaction_id, own_cheque)

    async def status(
        self, process_id: str, terminal_id: str | None = None
    ) -> tuple[OperationResult, dict[str, Any]]:
        current_id = terminal_id or (await self.device_info())[0].terminal_id
        if not current_id:
            raise ValueError("Smart POS did not provide terminalId")
        return await self.client.status(process_id, current_id)

    async def actualize(self, process_id: str) -> tuple[OperationResult, dict[str, Any]]:
        return await self.client.actualize(process_id)
