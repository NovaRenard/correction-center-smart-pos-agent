from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ..constants import AGENT_PROTOCOL_VERSION
from .commands import IncomingCommand

_COMMAND_ADAPTER: TypeAdapter[IncomingCommand] = TypeAdapter(IncomingCommand)


class UnknownCommandType(ValueError):
    pass


def parse_command(raw_message: str | bytes) -> IncomingCommand:
    try:
        payload = json.loads(raw_message)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Message is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Message must be a JSON object")
    message_type = payload.get("type")
    if message_type not in {"device.check", "payment.start", "refund.start"}:
        raise UnknownCommandType(str(message_type))
    return _COMMAND_ADAPTER.validate_python(payload)


def make_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": event_type,
        "protocolVersion": AGENT_PROTOCOL_VERSION,
        "messageId": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


def command_identity(command: IncomingCommand) -> tuple[str, str | None]:
    return command.command_id, command.operation_id


__all__ = [
    "IncomingCommand",
    "UnknownCommandType",
    "ValidationError",
    "command_identity",
    "make_event",
    "parse_command",
]
