"""Atomic persistence for non-secret desktop settings."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings, SmartPosTlsMode
from ..constants import DEFAULT_WINDOWS_DATA_DIRECTORY


class PersistentDesktopConfig(BaseModel):
    """The allow-list of values that may be written to config.json."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    agent_name: str = Field(default="Koshakan Smart POS Agent", min_length=1)
    crm_ws_url: str | None = None
    smart_pos_host: str | None = None
    smart_pos_port: int = Field(default=8080, ge=1, le=65535)
    smart_pos_client_name: str = Field(default="KoshakanSmartPosAgent", min_length=1)
    smart_pos_tls_mode: SmartPosTlsMode = SmartPosTlsMode.STRICT
    smart_pos_ca_bundle: Path | None = None
    smart_pos_request_timeout_seconds: float = Field(default=15, gt=0, le=120)
    heartbeat_interval_seconds: float = Field(default=15, gt=0)
    crm_reconnect_min_seconds: float = Field(default=1, gt=0)
    crm_reconnect_max_seconds: float = Field(default=60, gt=0)
    status_poll_interval_seconds: float = Field(default=1, gt=0)
    actualize_interval_seconds: float = Field(default=10, gt=0)
    unknown_actualize_timeout_seconds: float = Field(default=180, gt=0)
    log_level: str = "INFO"
    start_minimized: bool = False

    def is_complete(self) -> bool:
        return bool(self.agent_id and self.agent_name and self.crm_ws_url and self.smart_pos_host)

    def as_settings_values(self) -> dict[str, Any]:
        values = self.model_dump(exclude={"start_minimized"}, exclude_none=True, mode="python")
        return values


class DesktopConfigStore:
    """Stores desktop configuration outside the package and never stores credentials."""

    _ENVIRONMENT_KEYS = frozenset(Settings.model_fields)

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path()

    @staticmethod
    def default_path() -> Path:
        if os.environ.get("DEVELOPMENT_MODE", "").lower() in {"1", "true", "yes"}:
            return Path(".data") / "config.json"
        program_data = os.environ.get("PROGRAMDATA")
        root = Path(program_data) if program_data else DEFAULT_WINDOWS_DATA_DIRECTORY.parent
        return root / "KoshakanSmartPosAgent" / "config.json"

    def load(self) -> PersistentDesktopConfig:
        if not self.path.exists():
            config = PersistentDesktopConfig()
            self.save(config)
            return config
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config.json must contain an object")
        return PersistentDesktopConfig.model_validate(raw)

    def save(self, config: PersistentDesktopConfig) -> None:
        """Replace config.json atomically after serialising only the explicit allow-list."""
        payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

    def load_settings(self) -> Settings:
        """Environment and .env override persistent desktop values, then Settings defaults apply."""
        values = self.load().as_settings_values()
        values.update(self._environment_values())
        return Settings.model_validate(values)

    @classmethod
    def _environment_values(cls) -> dict[str, Any]:
        dotenv = dotenv_values(".env")
        merged: dict[str, Any] = {key: value for key, value in dotenv.items() if value is not None}
        merged.update(os.environ)
        result: dict[str, Any] = {}
        for name in cls._ENVIRONMENT_KEYS:
            environment_name = name.upper()
            if environment_name in merged:
                result[name] = merged[environment_name]
        return result
