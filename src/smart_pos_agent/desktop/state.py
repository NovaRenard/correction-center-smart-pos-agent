"""Typed state projection for the desktop UI.

The core emits small semantic events.  This module translates them into a stable,
log-independent view model; it deliberately has no Qt dependency.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class LifecycleStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class CrmStatus(StrEnum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    AUTHENTICATION_ERROR = "authentication_error"


class TerminalStatus(StrEnum):
    CHECKING = "checking"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    BUSY = "busy"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True, slots=True)
class AgentUiState:
    lifecycle_status: LifecycleStatus = LifecycleStatus.STARTING
    crm_status: CrmStatus = CrmStatus.DISCONNECTED
    terminal_status: TerminalStatus = TerminalStatus.CHECKING
    agent_id: str = ""
    agent_name: str = "Koshakan Smart POS Agent"
    agent_version: str = ""
    terminal_host: str = ""
    terminal_id: str | None = None
    serial_number: str | None = None
    pos_number: str | None = None
    last_heartbeat_at: datetime | None = None
    last_terminal_check_at: datetime | None = None
    active_operation_id: str | None = None
    active_operation_type: str | None = None
    active_operation_amount: int | None = None
    active_operation_status: str | None = None
    active_operation_sub_status: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    updated_at: datetime | None = None


_SECRET_VALUE = re.compile(
    r"(?i)\b(accessToken|refreshToken|CRM_AGENT_TOKEN|crm_agent_token)\s*([:=])\s*[^\s,;]+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")


def redact_ui_error(value: object) -> str:
    """Keep error dialogs useful without accidentally rendering credentials."""
    message = str(value)
    message = _BEARER.sub("Bearer •••", message)
    return _SECRET_VALUE.sub(lambda found: f"{found.group(1)}{found.group(2)}•••", message)


class AgentStateStore:
    """Thread-safe state mapper shared by the asyncio runtime and the Qt layer."""

    def __init__(self, initial: AgentUiState) -> None:
        self._state = initial
        self._lock = threading.Lock()

    def snapshot(self) -> AgentUiState:
        with self._lock:
            return self._state

    def set_lifecycle(self, status: LifecycleStatus, error: object | None = None) -> AgentUiState:
        changes: dict[str, Any] = {"lifecycle_status": status}
        if error is not None:
            changes.update(
                {
                    "last_error_code": error.__class__.__name__,
                    "last_error_message": redact_ui_error(error),
                }
            )
        return self._replace(**changes)

    def apply_core_event(self, event: str, payload: Mapping[str, Any]) -> AgentUiState:
        """Apply a core event without inspecting logs or changing wire protocol data."""
        if event == "crm.connecting":
            return self._replace(crm_status=CrmStatus.CONNECTING)
        if event == "crm.connected":
            return self._replace(crm_status=CrmStatus.CONNECTED)
        if event == "crm.reconnecting":
            return self._replace(crm_status=CrmStatus.RECONNECTING)
        if event == "crm.disconnected":
            return self._replace(
                crm_status=CrmStatus.DISCONNECTED,
                last_error_code=self._optional_string(payload.get("error")),
            )
        if event == "crm.authentication_error":
            return self._replace(
                crm_status=CrmStatus.AUTHENTICATION_ERROR,
                last_error_code="crm_authentication_error",
                last_error_message="CRM Agent Token не настроен или отклонён.",
            )
        if event == "crm.heartbeat":
            return self._replace(last_heartbeat_at=self._now())
        if event == "crm.hello":
            return self._apply_terminal(payload, ready_if_reachable=True)
        if event == "terminal.checking":
            return self._replace(terminal_status=TerminalStatus.CHECKING)
        if event == "terminal.ready":
            return self._apply_terminal(payload, ready_if_reachable=True)
        if event == "terminal.unavailable":
            return self._replace(
                terminal_status=TerminalStatus.UNAVAILABLE,
                last_terminal_check_at=self._now(),
                last_error_code=self._optional_string(payload.get("error")),
            )
        if event == "terminal.unauthorized":
            return self._replace(
                terminal_status=TerminalStatus.UNAUTHORIZED,
                last_terminal_check_at=self._now(),
                last_error_code=self._optional_string(payload.get("error")),
            )
        if event == "terminal.registration_started":
            return self._replace(terminal_status=TerminalStatus.CHECKING)
        if event == "operation.event":
            return self._apply_operation(payload)
        return self.snapshot()

    def _apply_terminal(
        self, payload: Mapping[str, Any], *, ready_if_reachable: bool
    ) -> AgentUiState:
        reachable = payload.get("reachable")
        status = TerminalStatus.READY if ready_if_reachable and reachable is not False else None
        return self._replace(
            **{
                **({"terminal_status": status} if status is not None else {}),
                "terminal_id": self._optional_string(payload.get("terminalId")),
                "serial_number": self._optional_string(payload.get("serialNumber")),
                "pos_number": self._optional_string(payload.get("posNum")),
                "last_terminal_check_at": self._now(),
            }
        )

    def _apply_operation(self, event: Mapping[str, Any]) -> AgentUiState:
        event_type = event.get("type")
        payload = event.get("payload")
        if not isinstance(event_type, str) or not isinstance(payload, Mapping):
            return self.snapshot()
        if event_type == "command.accepted":
            operation_type = self._optional_string(payload.get("operationType"))
            if operation_type not in {"payment", "refund"}:
                return self.snapshot()
            return self._replace(
                terminal_status=TerminalStatus.BUSY,
                active_operation_id=self._optional_string(payload.get("operationId")),
                active_operation_type=operation_type,
                active_operation_amount=self._optional_int(payload.get("amount")),
                active_operation_status="accepted",
                active_operation_sub_status=None,
            )
        operation_type = event_type.split(".", 1)[0]
        if operation_type not in {"payment", "refund"}:
            return self.snapshot()
        operation_id = self._optional_string(payload.get("operationId"))
        status = self._optional_string(payload.get("status"))
        sub_status = self._optional_string(payload.get("subStatus"))
        if event_type.endswith(".manual_review"):
            return self._replace(
                terminal_status=TerminalStatus.MANUAL_REVIEW,
                active_operation_id=operation_id,
                active_operation_type=operation_type,
                active_operation_status="manual_review",
                active_operation_sub_status=sub_status,
                last_error_code=self._optional_string(payload.get("errorCode")),
                last_error_message="Результат требует ручной проверки на терминале.",
            )
        if event_type.endswith(".completed") or event_type.endswith(".failed"):
            return self._replace(
                terminal_status=TerminalStatus.READY
                if event_type.endswith(".completed")
                else TerminalStatus.UNAVAILABLE,
                active_operation_id=None,
                active_operation_type=None,
                active_operation_amount=None,
                active_operation_status=None,
                active_operation_sub_status=None,
                last_error_code=self._optional_string(payload.get("errorCode")),
                last_error_message=(
                    "Операция не завершена на Smart POS."
                    if event_type.endswith(".failed")
                    else None
                ),
            )
        if event_type.endswith(".started") or event_type.endswith(".status"):
            return self._replace(
                terminal_status=TerminalStatus.BUSY,
                active_operation_id=operation_id,
                active_operation_type=operation_type,
                active_operation_amount=self._optional_int(payload.get("amount")),
                active_operation_status=status,
                active_operation_sub_status=sub_status,
            )
        return self.snapshot()

    def _replace(self, **changes: Any) -> AgentUiState:
        with self._lock:
            self._state = replace(self._state, **changes, updated_at=self._now())
            return self._state

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return value if isinstance(value, int) else None
