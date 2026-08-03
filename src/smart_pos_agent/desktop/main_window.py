"""Small Russian-language status window for the tray-first agent."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .resources import resource_path
from .runtime import AgentRuntime
from .state import AgentUiState, redact_ui_error


class MainWindow(QMainWindow):
    hidden_to_tray = Signal()

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        logs_directory: Path | None = None,
        open_settings: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.runtime = runtime
        self.logs_directory = logs_directory
        self.open_settings_callback = open_settings
        self.setWindowTitle("Koshakan Smart POS Agent")
        self.setWindowIcon(QIcon(str(resource_path("app.svg"))))
        self.setMinimumSize(550, 440)
        self._build_ui()
        runtime.state_changed.connect(self.set_state)
        runtime.action_failed.connect(self._show_action_error)
        self.set_state(runtime.state)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        heading = QLabel("Koshakan Smart POS Agent")
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(heading)

        crm_group = QGroupBox("CRM")
        crm_form = QFormLayout(crm_group)
        self.crm_status_label = QLabel()
        self.crm_url_label = QLabel()
        self.crm_last_label = QLabel()
        crm_reconnect_button = QPushButton("Переподключиться")
        crm_reconnect_button.clicked.connect(self.runtime.reconnect_crm)
        crm_form.addRow("Статус", self.crm_status_label)
        crm_form.addRow("URL", self.crm_url_label)
        crm_form.addRow("Последняя связь", self.crm_last_label)
        crm_form.addRow("", crm_reconnect_button)
        layout.addWidget(crm_group)

        pos_group = QGroupBox("Smart POS")
        pos_form = QFormLayout(pos_group)
        self.pos_status_label = QLabel()
        self.pos_host_label = QLabel()
        self.terminal_id_label = QLabel()
        self.serial_label = QLabel()
        self.pos_number_label = QLabel()
        pos_check_button = QPushButton("Проверить")
        pos_check_button.clicked.connect(self.runtime.get_device_info)
        pos_register_button = QPushButton("Подключить терминал")
        pos_register_button.clicked.connect(self._show_registration)
        buttons = QHBoxLayout()
        buttons.addWidget(pos_check_button)
        buttons.addWidget(pos_register_button)
        pos_form.addRow("Статус", self.pos_status_label)
        pos_form.addRow("IP и порт", self.pos_host_label)
        pos_form.addRow("terminalId", self.terminal_id_label)
        pos_form.addRow("serialNumber", self.serial_label)
        pos_form.addRow("posNum", self.pos_number_label)
        pos_form.addRow("", self._wrap_layout(buttons))
        layout.addWidget(pos_group)

        operation_group = QGroupBox("Текущая операция")
        operation_form = QFormLayout(operation_group)
        self.operation_label = QLabel("Агент готов к приёму оплаты")
        self.operation_label.setWordWrap(True)
        operation_form.addRow(self.operation_label)
        layout.addWidget(operation_group)

        bottom = QHBoxLayout()
        check_all = QPushButton("Проверить соединение")
        check_all.clicked.connect(self.runtime.check_connections)
        settings = QPushButton("Настройки")
        settings.clicked.connect(self._open_settings)
        logs = QPushButton("Открыть логи")
        logs.clicked.connect(self.open_logs)
        bottom.addWidget(check_all)
        bottom.addWidget(settings)
        bottom.addWidget(logs)
        layout.addLayout(bottom)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Агент запускается")

    @staticmethod
    def _wrap_layout(layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    @Slot(object)
    def set_state(self, state: AgentUiState) -> None:
        self.crm_status_label.setText(_crm_text(state.crm_status.value))
        self.crm_url_label.setText(_safe_url(getattr(self.runtime, "crm_url", "")))
        self.crm_last_label.setText(_format_time(state.last_heartbeat_at))
        self.pos_status_label.setText(_terminal_text(state.terminal_status.value))
        self.pos_host_label.setText(state.terminal_host or "—")
        self.terminal_id_label.setText(state.terminal_id or "—")
        self.serial_label.setText(state.serial_number or "—")
        self.pos_number_label.setText(state.pos_number or "—")
        self._set_operation(state)
        message = (
            "Агент работает"
            if state.lifecycle_status.value == "running"
            else state.lifecycle_status.value
        )
        if state.last_error_message:
            message = redact_ui_error(state.last_error_message)
        self.statusBar().showMessage(message)

    def _set_operation(self, state: AgentUiState) -> None:
        if not state.active_operation_id:
            self.operation_label.setText("Агент готов к приёму оплаты")
            return
        amount = (
            f"{state.active_operation_amount:,}".replace(",", " ")
            if state.active_operation_amount
            else "—"
        )
        operation_id = state.active_operation_id
        short_id = (
            operation_id if len(operation_id) <= 14 else f"{operation_id[:8]}…{operation_id[-4:]}"
        )
        operation_type = "Оплата" if state.active_operation_type == "payment" else "Возврат"
        self.operation_label.setText(
            f"{operation_type}: {amount} ₸\n"
            f"operationId: {short_id}\n"
            f"Статус: {state.active_operation_status or '—'} / "
            f"{state.active_operation_sub_status or '—'}"
        )

    def _show_registration(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Подключение Smart POS")
        layout = QVBoxLayout(dialog)
        instruction = QLabel(
            "1. Откройте настройки Smart POS.\n"
            "2. Перейдите в «Панель администратора».\n"
            "3. Откройте «Защита интеграции».\n"
            "4. Нажмите «Настроить доступ».\n"
            "5. Нажмите кнопку ниже и подтвердите запрос на терминале."
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        request = QPushButton("Отправить запрос регистрации")
        request.clicked.connect(self.runtime.register_smart_pos)
        request.clicked.connect(lambda: request.setText("Подтвердите запрос на Smart POS…"))
        layout.addWidget(request)
        dialog.exec()

    def _open_settings(self) -> None:
        if self.open_settings_callback is not None:
            self.open_settings_callback()

    def open_logs(self) -> None:
        if self.logs_directory is not None:
            self.logs_directory.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.logs_directory)))

    @Slot(str, str)
    def _show_action_error(self, _action: str, message: str) -> None:
        self.statusBar().showMessage(redact_ui_error(message), 10_000)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()
        self.hidden_to_tray.emit()


def _safe_url(value: str) -> str:
    if not value:
        return "—"
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _format_time(value: datetime | None) -> str:
    return value.astimezone().strftime("%H:%M:%S") if value is not None else "—"


def _crm_text(status: str) -> str:
    return {
        "connecting": "подключается",
        "connected": "подключена",
        "reconnecting": "переподключается",
        "disconnected": "нет соединения",
        "authentication_error": "ошибка авторизации",
    }.get(status, status)


def _terminal_text(status: str) -> str:
    return {
        "checking": "проверяется",
        "ready": "готов",
        "unavailable": "недоступен",
        "unauthorized": "не авторизован",
        "busy": "выполняет операцию",
        "manual_review": "нужна ручная проверка",
    }.get(status, status)
