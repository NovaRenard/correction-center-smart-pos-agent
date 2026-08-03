from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .constants import DEFAULT_WINDOWS_DATA_DIRECTORY


class SmartPosTlsMode(StrEnum):
    STRICT = "strict"
    CUSTOM_CA = "custom_ca"
    IP_INSECURE = "ip_insecure"


class Settings(BaseSettings):
    """Runtime configuration loaded from environment or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    agent_id: str = Field(min_length=1)
    agent_name: str = Field(default="Koshakan Smart POS Agent", min_length=1)
    agent_version: str = "0.1.0"
    crm_ws_url: str
    crm_agent_token: str | None = None

    smart_pos_host: str = Field(min_length=1)
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

    data_directory: Path | None = None
    log_level: str = "INFO"
    development_mode: bool = False

    @field_validator("crm_ws_url")
    @classmethod
    def websocket_url_must_be_secure(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"wss", "ws"} or not parsed.netloc:
            raise ValueError("CRM_WS_URL must use ws or wss")
        return value

    @model_validator(mode="after")
    def validate_cross_field_values(self) -> Settings:
        if self.crm_reconnect_min_seconds > self.crm_reconnect_max_seconds:
            raise ValueError("CRM_RECONNECT_MIN_SECONDS cannot exceed CRM_RECONNECT_MAX_SECONDS")
        if self.smart_pos_tls_mode is SmartPosTlsMode.CUSTOM_CA and not self.smart_pos_ca_bundle:
            raise ValueError("SMART_POS_CA_BUNDLE is required for custom_ca mode")
        if self.smart_pos_ca_bundle and not self.smart_pos_ca_bundle.exists():
            raise ValueError("SMART_POS_CA_BUNDLE does not exist")
        return self

    @property
    def resolved_data_directory(self) -> Path:
        if self.data_directory is not None:
            return self.data_directory.expanduser().resolve()
        if self.development_mode:
            return Path(".data").resolve()
        program_data = os.environ.get("PROGRAMDATA")
        if program_data:
            return Path(program_data) / "KoshakanSmartPosAgent"
        return DEFAULT_WINDOWS_DATA_DIRECTORY

    @property
    def smart_pos_base_url(self) -> str:
        return f"https://{self.smart_pos_host}:{self.smart_pos_port}/v2"
