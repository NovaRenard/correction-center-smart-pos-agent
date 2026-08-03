from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

import keyring
from keyring.errors import KeyringError

from ..constants import KEYRING_SERVICE

logger = logging.getLogger(__name__)


class SecretStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...

    def is_available(self) -> bool: ...


class KeyringSecretStore:
    """Secret store backed by the operating system credential manager."""

    def __init__(self, service_name: str = KEYRING_SERVICE) -> None:
        self.service_name = service_name

    def get(self, key: str) -> str | None:
        try:
            return keyring.get_password(self.service_name, key)
        except KeyringError as exc:
            logger.error("secret_store_read_failed: %s", exc.__class__.__name__)
            return None

    def set(self, key: str, value: str) -> None:
        try:
            keyring.set_password(self.service_name, key, value)
        except KeyringError as exc:
            logger.error("secret_store_write_failed: %s", exc.__class__.__name__)
            raise RuntimeError("Windows Credential Manager is unavailable") from exc

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(self.service_name, key)
        except keyring.errors.PasswordDeleteError:
            return
        except KeyringError as exc:
            logger.error("secret_store_delete_failed: %s", exc.__class__.__name__)
            raise RuntimeError("Windows Credential Manager is unavailable") from exc

    def is_available(self) -> bool:
        try:
            return keyring.get_keyring().priority > 0
        except KeyringError as exc:
            logger.warning("secret_store_check_failed: %s", exc.__class__.__name__)
            return False


class InMemorySecretStore:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values = dict(initial or {})

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def is_available(self) -> bool:
        return True


class DevelopmentFileSecretStore:
    """Explicitly opt-in development-only fallback; never selected in production."""

    def __init__(self, path: Path) -> None:
        self.path = path
        logger.warning("development_secret_store_enabled")

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        parsed = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
        ):
            raise ValueError("Development secrets file has an invalid format")
        return parsed

    def _write(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(values), encoding="utf-8")

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def set(self, key: str, value: str) -> None:
        values = self._read()
        values[key] = value
        self._write(values)

    def delete(self, key: str) -> None:
        values = self._read()
        values.pop(key, None)
        self._write(values)

    def is_available(self) -> bool:
        return True
