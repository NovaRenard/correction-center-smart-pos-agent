"""Tray icon, compact status tooltip, and desktop-only actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl, Slot
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

from . import autostart
from .config_store import DesktopConfigStore
from .main_window import MainWindow
from .notifications import NotificationDeduplicator
from .resources import resource_path
from .runtime import AgentRuntime
from .state import AgentUiState


class TrayController(QSystemTrayIcon):
    def __init__(
        self,
        runtime: AgentRuntime,
        window: MainWindow,
        config_store: DesktopConfigStore,
        *,
        data_directory: Path,
    ) -> None:
        super().__init__(QIcon(str(resource_path("tray-offline.svg"))), window)
        self.runtime = runtime
        self.window = window
        self.config_store = config_store
        self.data_directory = data_directory
        self._notices = NotificationDeduplicator()
        self._hidden_notice_sent = False
        self._autostart_action: QAction | None = None
        self.setContextMenu(self._build_menu())
        self.activated.connect(self._activated)
        runtime.state_changed.connect(self.set_state)
        runtime.core_event.connect(self._on_core_event)
        runtime.stopped.connect(self._quit_application)
        window.hidden_to_tray.connect(self._window_hidden)
        self.set_state(runtime.state)

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        open_action = menu.addAction("Открыть")
        open_action.triggered.connect(self.open_window)
        check_action = menu.addAction("Проверить соединение")
        check_action.triggered.connect(self.runtime.check_connections)
        reconnect_action = menu.addAction("Переподключиться к CRM")
        reconnect_action.triggered.connect(self.runtime.reconnect_crm)
        register_action = menu.addAction("Подключить Smart POS")
        register_action.triggered.connect(self.window._show_registration)
        menu.addSeparator()
        logs_action = menu.addAction("Открыть папку логов")
        logs_action.triggered.connect(self.window.open_logs)
        data_action = menu.addAction("Открыть папку данных")
        data_action.triggered.connect(self._open_data_directory)
        settings_action = menu.addAction("Настройки")
        settings_action.triggered.connect(self.window._open_settings)
        autostart_action = menu.addAction("Запускать вместе с Windows")
        autostart_action.setCheckable(True)
        autostart_action.setChecked(autostart.is_enabled())
        autostart_action.triggered.connect(self._toggle_autostart)
        self._autostart_action = autostart_action
        menu.addSeparator()
        about_action = menu.addAction("О программе")
        about_action.triggered.connect(self._show_about)
        exit_action = menu.addAction("Выход")
        exit_action.triggered.connect(self.request_exit)
        return menu

    @Slot(object)
    def set_state(self, state: AgentUiState) -> None:
        icon = "tray-warning.svg"
        if state.lifecycle_status.value in {"stopped", "stopping"}:
            icon = "tray-offline.svg"
        elif state.terminal_status.value == "busy":
            icon = "tray-busy.svg"
        elif state.crm_status.value == "connected" and state.terminal_status.value == "ready":
            icon = "tray-ready.svg"
        elif state.crm_status.value in {
            "disconnected",
            "authentication_error",
        } or state.terminal_status.value in {
            "unavailable",
            "manual_review",
            "unauthorized",
        }:
            icon = "tray-error.svg"
        self.setIcon(QIcon(str(resource_path(icon))))
        state_line = (
            "ожидание оплаты"
            if state.terminal_status.value == "ready"
            else state.terminal_status.value
        )
        self.setToolTip(
            "Koshakan Smart POS Agent\n"
            f"CRM: {state.crm_status.value}\n"
            f"Smart POS: {state.terminal_status.value}\n"
            f"Состояние: {state_line}"
        )

    @Slot(str, object)
    def _on_core_event(self, event: str, raw: object) -> None:
        payload = raw if isinstance(raw, dict) else {}
        if event == "terminal.unavailable":
            self._notify(
                "terminal-unavailable",
                "Smart POS недоступен",
                "Проверьте сеть и питание терминала",
                QSystemTrayIcon.MessageIcon.Warning,
            )
        if event != "operation.event":
            return
        event_type = payload.get("type")
        operation = payload.get("payload")
        if not isinstance(event_type, str) or not isinstance(operation, dict):
            return
        amount = operation.get("amount")
        amount_text = f"{amount:,}".replace(",", " ") if isinstance(amount, int) else ""
        if event_type.endswith(".completed"):
            self._notify(
                f"completed-{operation.get('operationId')}",
                "Оплата принята" if event_type.startswith("payment.") else "Возврат выполнен",
                f"{amount_text} ₸ через {operation.get('method') or 'Smart POS'}".strip(),
                QSystemTrayIcon.MessageIcon.Information,
            )
        elif event_type.endswith(".manual_review"):
            self._notify(
                f"review-{operation.get('operationId')}",
                "Результат оплаты требует проверки",
                "Не запускайте повторную оплату до сверки с терминалом",
                QSystemTrayIcon.MessageIcon.Warning,
            )
        elif event_type.endswith(".failed"):
            self._notify(
                f"failed-{operation.get('operationId')}",
                "Оплата не завершена"
                if event_type.startswith("payment.")
                else "Возврат не завершён",
                "Покупатель отменил операцию или терминал вернул ошибку",
                QSystemTrayIcon.MessageIcon.Critical,
            )

    def _notify(
        self, key: str, title: str, message: str, icon: QSystemTrayIcon.MessageIcon
    ) -> None:
        if self._notices.should_show(key):
            self.showMessage(title, message, icon, 10_000)

    @Slot()
    def _window_hidden(self) -> None:
        if not self._hidden_notice_sent:
            self._hidden_notice_sent = True
            self._notify(
                "window-hidden",
                "Koshakan Smart POS Agent",
                "Приложение продолжает работать в системном трее",
                QSystemTrayIcon.MessageIcon.Information,
            )

    @Slot(QSystemTrayIcon.ActivationReason)
    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.open_window()

    @Slot()
    def open_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    @Slot(bool)
    def _toggle_autostart(self, enabled: bool) -> None:
        try:
            if enabled:
                autostart.enable(autostart.current_gui_executable())
            else:
                autostart.disable()
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self.window, "Автозапуск", str(exc))
            if self._autostart_action is not None:
                self._autostart_action.setChecked(not enabled)

    @Slot()
    def _open_data_directory(self) -> None:
        self.data_directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_directory)))

    @Slot()
    def _show_about(self) -> None:
        state = self.runtime.state
        QMessageBox.information(
            self.window,
            "О программе",
            f"Koshakan Smart POS Agent\nВерсия {state.agent_version or '—'}\n"
            "Использует официальный локальный Smart POS API.",
        )

    @Slot()
    def request_exit(self) -> None:
        if self.runtime.state.active_operation_id and not self.confirm_active_operation_exit():
            return
        self.hide()
        self.runtime.stop()

    def confirm_active_operation_exit(self) -> bool:
        dialog = QMessageBox(self.window)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Операция выполняется")
        dialog.setText(
            "Сейчас выполняется операция на Smart POS.\n\n"
            "Завершение агента не отменит операцию на терминале. Результат может "
            "потребовать ручной проверки."
        )
        no_button = dialog.addButton("Не выходить", QMessageBox.ButtonRole.NoRole)
        dialog.addButton("Всё равно выйти", QMessageBox.ButtonRole.YesRole)
        dialog.setDefaultButton(no_button)
        dialog.exec()
        return dialog.clickedButton() is not no_button

    @Slot()
    def _quit_application(self) -> None:
        application = QCoreApplication.instance()
        if application is not None:
            application.quit()
