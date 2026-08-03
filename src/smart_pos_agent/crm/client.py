from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from ..config import Settings
from ..operations.manager import OperationManager
from ..smart_pos.exceptions import SmartPosError
from ..storage.secret_store import SecretStore
from .commands import DeviceCheckCommand, PaymentStartCommand, RefundStartCommand
from .protocol import UnknownCommandType, make_event, parse_command
from .reconnect import ExponentialBackoff

logger = logging.getLogger(__name__)


class CrmClient:
    """Outgoing, reconnecting WebSocket connection to Correction Center CRM."""

    def __init__(
        self, settings: Settings, secret_store: SecretStore, operations: OperationManager
    ) -> None:
        self.settings = settings
        self.secret_store = secret_store
        self.operations = operations
        self.operations.set_event_sink(self.send_event)
        self._socket: ClientConnection | None = None
        self._send_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._backoff = ExponentialBackoff(
            settings.crm_reconnect_min_seconds, settings.crm_reconnect_max_seconds
        )

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                token = self._crm_token()
                async with connect(
                    self.settings.crm_ws_url,
                    additional_headers={"Authorization": f"Bearer {token}"},
                    open_timeout=self.settings.smart_pos_request_timeout_seconds,
                ) as socket:
                    self._socket = socket
                    self._backoff.reset()
                    logger.info("crm_connected")
                    await self._send_hello()
                    await self.operations.resume_incomplete()
                    await self._run_session(socket)
            except (OSError, TimeoutError, WebSocketException) as exc:
                logger.warning("crm_connection_lost class=%s", exc.__class__.__name__)
            finally:
                self._socket = None
            if not self._stop.is_set():
                delay = self._backoff.next_delay()
                logger.info("crm_reconnect_wait seconds=%.2f", delay)
                await asyncio.sleep(delay)

    def stop(self) -> None:
        self._stop.set()

    async def check_connection(self) -> None:
        """Open and close an authenticated socket for the doctor command."""
        token = self._crm_token()
        try:
            async with connect(
                self.settings.crm_ws_url,
                additional_headers={"Authorization": f"Bearer {token}"},
                open_timeout=self.settings.smart_pos_request_timeout_seconds,
            ):
                return
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise ConnectionError("CRM WebSocket is unreachable") from exc

    async def _run_session(self, socket: ClientConnection) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_loop(), name="crm-heartbeat")
        try:
            async for raw_message in socket:
                await self._handle_message(raw_message)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat_loop(self) -> None:
        while self._socket is not None:
            await asyncio.sleep(self.settings.heartbeat_interval_seconds)
            if self._socket is None:
                return
            await self.send_event(
                make_event(
                    "agent.heartbeat",
                    {
                        "agentId": self.settings.agent_id,
                        "terminalStatus": "busy"
                        if self.operations.active_operation_id()
                        else "ready",
                        "activeOperationId": self.operations.active_operation_id(),
                    },
                )
            )

    async def _send_hello(self) -> None:
        terminal: dict[str, Any] = {
            "reachable": False,
            "terminalId": None,
            "serialNumber": None,
            "posNum": None,
        }
        try:
            info, _ = await self.operations.smart_pos.device_info(refresh=True)
            terminal = {
                "reachable": True,
                "terminalId": info.terminal_id,
                "serialNumber": info.serial_num,
                "posNum": info.pos_num,
            }
        except (SmartPosError, ConnectionError, OSError, ValueError) as exc:
            logger.warning("hello_terminal_check_failed class=%s", exc.__class__.__name__)
        await self.send_event(
            make_event(
                "agent.hello",
                {
                    "agentId": self.settings.agent_id,
                    "agentName": self.settings.agent_name,
                    "agentVersion": self.settings.agent_version,
                    "platform": "windows",
                    "terminal": terminal,
                },
            )
        )

    async def _handle_message(self, raw_message: str | bytes) -> None:
        try:
            command = parse_command(raw_message)
        except UnknownCommandType as exc:
            await self.send_event(
                make_event("protocol.error", {"code": "unknown_command", "message": str(exc)})
            )
            return
        except (ValueError, ValidationError) as exc:
            logger.warning("crm_protocol_invalid class=%s", exc.__class__.__name__)
            await self.send_event(
                make_event("protocol.error", {"code": "invalid_command", "message": str(exc)})
            )
            return
        if isinstance(command, DeviceCheckCommand):
            await self.operations.handle_device_check(command)
        elif isinstance(command, PaymentStartCommand):
            await self.operations.handle_payment(command)
        elif isinstance(command, RefundStartCommand):
            await self.operations.handle_refund(command)

    async def send_event(self, event: dict[str, Any]) -> None:
        socket = self._socket
        if socket is None:
            logger.info("crm_event_not_sent_disconnected type=%s", event.get("type"))
            return
        message = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        async with self._send_lock:
            try:
                await socket.send(message)
            except WebSocketException as exc:
                logger.warning("crm_event_send_failed class=%s", exc.__class__.__name__)
                raise

    def _crm_token(self) -> str:
        stored = self.secret_store.get("crm_agent_token")
        if stored:
            return stored
        if self.settings.crm_agent_token:
            self.secret_store.set("crm_agent_token", self.settings.crm_agent_token)
            return self.settings.crm_agent_token
        raise ConnectionError("CRM_AGENT_TOKEN is not configured")
