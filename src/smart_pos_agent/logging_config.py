from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_SECRET_KEY = re.compile(
    r"(access.?token|refresh.?token|authorization|secret|token)", re.IGNORECASE
)
_BEARER = re.compile(r"(Bearer\s+)[^\s,]+", re.IGNORECASE)


def redact_value(value: Any) -> Any:
    """Remove credential-bearing fields recursively before persistence or logging."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SECRET_KEY.search(key) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return _BEARER.sub(r"\1[REDACTED]", value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _BEARER.sub(r"\1[REDACTED]", str(record.msg))
        if record.args:
            record.args = redact_value(record.args)
        return True


class ContextFilter(logging.Filter):
    def __init__(self, agent_id: str) -> None:
        super().__init__()
        self.agent_id = agent_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "agent_id"):
            record.agent_id = self.agent_id
        if not hasattr(record, "operation_id"):
            record.operation_id = "-"
        if not hasattr(record, "event"):
            record.event = record.getMessage().split(" ", maxsplit=1)[0]
        return True


def configure_logging(log_directory: Path, level: str, agent_id: str) -> None:
    log_directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s event=%(event)s agentId=%(agent_id)s "
        "operationId=%(operation_id)s %(message)s"
    )
    redactor = RedactingFilter()
    context = ContextFilter(agent_id)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        RotatingFileHandler(
            log_directory / "agent.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        ),
    ]
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(redactor)
        handler.addFilter(context)
    logging.basicConfig(level=level.upper(), handlers=handlers, force=True)


def json_for_storage(value: Any) -> str:
    return json.dumps(redact_value(value), ensure_ascii=False, separators=(",", ":"), default=str)
