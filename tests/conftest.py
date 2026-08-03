from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from smart_pos_agent.config import Settings
from smart_pos_agent.storage.database import Database
from smart_pos_agent.storage.operation_repository import OperationRepository
from smart_pos_agent.storage.secret_store import InMemorySecretStore


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "agent_id": "agent-test",
            "agent_name": "Test Agent",
            "agent_version": "0.1.0-test",
            "crm_ws_url": "ws://127.0.0.1:8765",
            "crm_agent_token": "crm-secret",
            "smart_pos_host": "192.0.2.10",
            "smart_pos_tls_mode": "strict",
            "data_directory": str(tmp_path / "data"),
            "status_poll_interval_seconds": 0.001,
            "actualize_interval_seconds": 0.002,
            "unknown_actualize_timeout_seconds": 0.02,
            "crm_reconnect_min_seconds": 0.001,
            "crm_reconnect_max_seconds": 0.002,
        }
    )


@pytest.fixture
def secrets() -> InMemorySecretStore:
    return InMemorySecretStore()


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[OperationRepository]:
    database = Database(tmp_path / "agent.sqlite3")
    database.initialize()
    yield OperationRepository(database)
    database.close()
