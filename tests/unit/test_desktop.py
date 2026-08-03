from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from smart_pos_agent.desktop.autostart import build_enable_command
from smart_pos_agent.desktop.config_store import DesktopConfigStore, PersistentDesktopConfig
from smart_pos_agent.desktop.first_run import FirstRunWizard
from smart_pos_agent.desktop.main import smoke_test
from smart_pos_agent.desktop.main_window import MainWindow
from smart_pos_agent.desktop.notifications import NotificationDeduplicator
from smart_pos_agent.desktop.settings_window import SettingsWindow
from smart_pos_agent.desktop.single_instance import SingleInstance
from smart_pos_agent.desktop.state import (
    AgentStateStore,
    AgentUiState,
    CrmStatus,
    LifecycleStatus,
    TerminalStatus,
    redact_ui_error,
)
from smart_pos_agent.desktop.tray import TrayController
from smart_pos_agent.storage.secret_store import InMemorySecretStore


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication(["desktop-tests"])


class FakeRuntime(QObject):
    state_changed = Signal(object)
    core_event = Signal(str, object)
    action_completed = Signal(str, object)
    action_failed = Signal(str, str)
    stopped = Signal()

    def __init__(self, state: AgentUiState | None = None) -> None:
        super().__init__()
        self.state = state or AgentUiState(lifecycle_status=LifecycleStatus.RUNNING)
        self.crm_url = "wss://crm.example.test/agent?token=never-show"
        self.stop_calls = 0

    def check_connections(self) -> None:
        return None

    def register_smart_pos(self) -> None:
        return None

    def get_device_info(self) -> None:
        return None

    def reconnect_crm(self) -> None:
        return None

    def stop(self) -> None:
        self.stop_calls += 1


def _operation_event(event_type: str, **payload: object) -> dict[str, object]:
    return {"type": event_type, "payload": payload}


def _config_store(tmp_path: Path) -> DesktopConfigStore:
    store = DesktopConfigStore(tmp_path / "config.json")
    store.save(
        PersistentDesktopConfig(
            agent_id="agent-1",
            agent_name="Тестовый агент",
            crm_ws_url="wss://crm.example.test/agent",
            smart_pos_host="192.168.1.10",
        )
    )
    return store


def test_agent_ui_state_defaults() -> None:
    state = AgentUiState()
    assert state.lifecycle_status is LifecycleStatus.STARTING
    assert state.crm_status is CrmStatus.DISCONNECTED
    assert state.terminal_status is TerminalStatus.CHECKING
    assert state.active_operation_id is None


def test_state_maps_connected_and_ready() -> None:
    store = AgentStateStore(AgentUiState())
    store.apply_core_event("crm.connected", {})
    result = store.apply_core_event(
        "terminal.ready",
        {"terminalId": "terminal-1", "serialNumber": "serial-1", "posNum": "5"},
    )
    assert result.crm_status is CrmStatus.CONNECTED
    assert result.terminal_status is TerminalStatus.READY
    assert result.terminal_id == "terminal-1"


def test_state_maps_reconnect_and_unavailable() -> None:
    store = AgentStateStore(AgentUiState())
    store.apply_core_event("crm.reconnecting", {"delay": 1})
    result = store.apply_core_event("terminal.unavailable", {"error": "SmartPosTransportError"})
    assert result.crm_status is CrmStatus.RECONNECTING
    assert result.terminal_status is TerminalStatus.UNAVAILABLE


def test_state_maps_busy_and_manual_review() -> None:
    store = AgentStateStore(AgentUiState())
    accepted = store.apply_core_event(
        "operation.event",
        _operation_event(
            "command.accepted",
            operationId="operation-123",
            operationType="payment",
            amount=25000,
            status="accepted",
        ),
    )
    busy = store.apply_core_event(
        "operation.event",
        _operation_event(
            "payment.started",
            operationId="operation-123",
            amount=25000,
            status="wait",
            subStatus="qr",
        ),
    )
    review = store.apply_core_event(
        "operation.event",
        _operation_event(
            "payment.manual_review",
            operationId="operation-123",
            errorCode="unknown_timeout",
        ),
    )
    assert accepted.terminal_status is TerminalStatus.BUSY
    assert busy.terminal_status is TerminalStatus.BUSY
    assert busy.active_operation_amount == 25000
    assert review.terminal_status is TerminalStatus.MANUAL_REVIEW
    assert review.active_operation_status == "manual_review"


def test_close_window_hides_to_tray(qapp: QApplication) -> None:
    window = MainWindow(FakeRuntime())  # type: ignore[arg-type]
    window.show()
    qapp.processEvents()
    window.close()
    qapp.processEvents()
    assert not window.isVisible()


def test_tray_exit_stops_runtime(qapp: QApplication, tmp_path: Path) -> None:
    runtime = FakeRuntime()
    window = MainWindow(runtime)  # type: ignore[arg-type]
    tray = TrayController(runtime, window, _config_store(tmp_path), data_directory=tmp_path)
    tray.request_exit()
    assert runtime.stop_calls == 1


def test_active_operation_exit_requires_confirmation(qapp: QApplication, tmp_path: Path) -> None:
    runtime = FakeRuntime(AgentUiState(active_operation_id="operation-1"))
    window = MainWindow(runtime)  # type: ignore[arg-type]
    tray = TrayController(runtime, window, _config_store(tmp_path), data_directory=tmp_path)
    tray.confirm_active_operation_exit = lambda: False  # type: ignore[method-assign]
    tray.request_exit()
    assert runtime.stop_calls == 0


def test_settings_never_display_existing_secret(qapp: QApplication, tmp_path: Path) -> None:
    secrets = InMemorySecretStore({"crm_agent_token": "very-secret-value"})
    window = SettingsWindow(_config_store(tmp_path), secrets)
    assert window.crm_token_edit.text() == ""
    assert not window.crm_token_edit.isEnabled()
    assert "защищённом" in window.crm_token_edit.placeholderText()


def test_settings_save_token_in_secret_store_not_config(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _config_store(tmp_path)
    secrets = InMemorySecretStore()
    monkeypatch.setattr(SettingsWindow, "_apply_autostart", staticmethod(lambda _enabled: None))
    window = SettingsWindow(store, secrets, first_run=True)
    window.crm_token_edit.setText("secret-from-ui")
    assert window.save()
    assert secrets.get("crm_agent_token") == "secret-from-ui"
    contents = json.loads(store.path.read_text(encoding="utf-8"))
    assert "crm_agent_token" not in contents
    assert "secret-from-ui" not in store.path.read_text(encoding="utf-8")


def test_first_run_wizard_is_available(qapp: QApplication, tmp_path: Path) -> None:
    wizard = FirstRunWizard(_config_store(tmp_path), InMemorySecretStore())
    assert wizard.windowTitle() == "Первичная настройка"


def test_single_instance_lock(tmp_path: Path) -> None:
    first = SingleInstance(tmp_path)
    second = SingleInstance(tmp_path)
    assert first.acquire()
    assert not second.acquire()
    first.release()


def test_autostart_command_contains_no_secret() -> None:
    command = build_enable_command(Path(r"C:\Program Files\Agent\KoshakanSmartPosAgent.exe"))
    rendered = " ".join(command).lower()
    assert "secret" not in rendered
    assert "token" not in rendered
    assert "KoshakanSmartPosAgent.exe" in command[-2]


def test_gui_smoke_test(qapp: QApplication) -> None:
    assert smoke_test() == 0


def test_ui_error_redaction_and_notification_deduplication() -> None:
    redacted = redact_ui_error("Bearer abc; CRM_AGENT_TOKEN=private accessToken: other")
    assert "abc" not in redacted
    assert "private" not in redacted
    assert "other" not in redacted
    notices = NotificationDeduplicator(cooldown_seconds=30)
    assert notices.should_show("same", now=10)
    assert not notices.should_show("same", now=11)
    assert notices.should_show("same", now=41)
