"""Entry point for the windowed Windows tray application."""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from ..storage.secret_store import DevelopmentFileSecretStore, KeyringSecretStore, SecretStore
from ..version import __version__
from .config_store import DesktopConfigStore
from .first_run import FirstRunWizard
from .main_window import MainWindow
from .resources import resource_path
from .runtime import AgentRuntime
from .settings_window import SettingsWindow
from .single_instance import SingleInstance
from .state import AgentUiState, LifecycleStatus
from .tray import TrayController


class _SmokeRuntime(QObject):
    """No-network runtime used only by --smoke-test in CI."""

    state_changed = Signal(object)
    core_event = Signal(str, object)
    action_completed = Signal(str, object)
    action_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.state = AgentUiState(
            lifecycle_status=LifecycleStatus.STOPPED,
            agent_version=__version__,
        )
        self.crm_url = ""

    def check_connections(self) -> None:
        return None

    def register_smart_pos(self) -> None:
        return None

    def get_device_info(self) -> None:
        return None

    def reconnect_crm(self) -> None:
        return None


def _secret_store(config_store: DesktopConfigStore) -> SecretStore:
    development = os.environ.get("DEVELOPMENT_MODE", "").lower() in {"1", "true", "yes"}
    if development:
        return DevelopmentFileSecretStore(config_store.path.parent / "secrets.json")
    return KeyringSecretStore()


def smoke_test() -> int:
    application = QApplication.instance() or QApplication(["KoshakanSmartPosAgent", "--smoke-test"])
    assert isinstance(application, QApplication)
    for name in (
        "app.svg",
        "tray-ready.svg",
        "tray-warning.svg",
        "tray-error.svg",
        "tray-busy.svg",
    ):
        if not resource_path(name).is_file():
            raise RuntimeError(f"Не найден ресурс: {name}")
    window = MainWindow(_SmokeRuntime())  # type: ignore[arg-type]
    window.hide()
    window.deleteLater()
    application.processEvents()
    return 0


def run_desktop() -> int:
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)
    config_store = DesktopConfigStore()
    instance = SingleInstance(config_store.path.parent)
    if not instance.acquire():
        QMessageBox.warning(
            None,
            "Koshakan Smart POS Agent",
            "Приложение уже запущено. Откройте значок возле часов.",
        )
        return 0
    application.aboutToQuit.connect(instance.release)
    secret_store = _secret_store(config_store)
    config = config_store.load()
    if not config.is_complete() or not secret_store.get("crm_agent_token"):
        wizard = FirstRunWizard(config_store, secret_store)
        if wizard.exec() != wizard.DialogCode.Accepted:
            return 0
        config = config_store.load()
    runtime = AgentRuntime(config_store.load_settings, secret_store)

    def open_settings() -> None:
        dialog = SettingsWindow(config_store, secret_store, parent=window)
        if dialog.exec() == dialog.DialogCode.Accepted:
            QMessageBox.information(
                window,
                "Настройки сохранены",
                "Изменения подключения будут применены после перезапуска агента.",
            )

    window = MainWindow(
        runtime,
        logs_directory=config_store.path.parent / "logs",
        open_settings=open_settings,
    )
    tray = TrayController(runtime, window, config_store, data_directory=config_store.path.parent)
    tray.show()
    runtime.start()
    if not config.start_minimized:
        window.show()
    return application.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Koshakan Smart POS Agent")
    parser.add_argument("--version", action="store_true", help="Показать версию")
    parser.add_argument("--smoke-test", action="store_true", help="Проверить запуск GUI без сети")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.smoke_test:
        return smoke_test()
    return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
