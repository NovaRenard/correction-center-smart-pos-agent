"""Desktop settings editor.  Only the CRM token is sent to SecretStore."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, SmartPosTlsMode
from ..storage.secret_store import SecretStore
from . import autostart
from .config_store import DesktopConfigStore, PersistentDesktopConfig


class SettingsWindow(QDialog):
    configuration_saved = Signal()

    def __init__(
        self,
        config_store: DesktopConfigStore,
        secret_store: SecretStore,
        *,
        first_run: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config_store = config_store
        self.secret_store = secret_store
        self.first_run = first_run
        self._token_replacement_requested = first_run or not bool(
            secret_store.get("crm_agent_token")
        )
        self.setWindowTitle("Первичная настройка" if first_run else "Настройки")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load_values(config_store.load())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.agent_name_edit = QLineEdit()
        self.crm_url_edit = QLineEdit()
        self.crm_token_edit = QLineEdit()
        self.crm_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.replace_token_button = QPushButton("Заменить CRM Agent Token")
        self.replace_token_button.clicked.connect(self._enable_token_replacement)
        token_row = QHBoxLayout()
        token_row.addWidget(self.crm_token_edit)
        token_row.addWidget(self.replace_token_button)
        self.smart_pos_host_edit = QLineEdit()
        self.smart_pos_port_spin = QSpinBox()
        self.smart_pos_port_spin.setRange(1, 65535)
        self.client_name_edit = QLineEdit()
        self.tls_mode_combo = QComboBox()
        for mode in SmartPosTlsMode:
            self.tls_mode_combo.addItem(mode.value, mode)
        self.ca_bundle_edit = QLineEdit()
        self.start_minimized_check = QCheckBox("Запускать свёрнутым в трей")
        self.autostart_check = QCheckBox("Запускать вместе с Windows")
        form.addRow("Название компьютера / агента", self.agent_name_edit)
        form.addRow("CRM WebSocket URL", self.crm_url_edit)
        form.addRow("CRM Agent Token", self._wrap_layout(token_row))
        form.addRow("IP Smart POS", self.smart_pos_host_edit)
        form.addRow("Порт Smart POS", self.smart_pos_port_spin)
        form.addRow("Имя клиента Smart POS", self.client_name_edit)
        form.addRow("TLS mode", self.tls_mode_combo)
        form.addRow("Путь custom CA", self.ca_bundle_edit)
        root.addLayout(form)
        root.addWidget(self.start_minimized_check)
        root.addWidget(self.autostart_check)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        if self.first_run:
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Выйти")
        root.addWidget(buttons)

    @staticmethod
    def _wrap_layout(layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _load_values(self, config: PersistentDesktopConfig) -> None:
        self.agent_name_edit.setText(config.agent_name)
        self.crm_url_edit.setText(config.crm_ws_url or "")
        self.smart_pos_host_edit.setText(config.smart_pos_host or "")
        self.smart_pos_port_spin.setValue(config.smart_pos_port)
        self.client_name_edit.setText(config.smart_pos_client_name)
        self.tls_mode_combo.setCurrentText(config.smart_pos_tls_mode.value)
        self.ca_bundle_edit.setText(str(config.smart_pos_ca_bundle or ""))
        self.start_minimized_check.setChecked(config.start_minimized)
        self.autostart_check.setChecked(autostart.is_enabled())
        if not self._token_replacement_requested:
            self.crm_token_edit.setEnabled(False)
            self.crm_token_edit.setPlaceholderText("Сохранён в защищённом хранилище")

    def _enable_token_replacement(self) -> None:
        self._token_replacement_requested = True
        self.crm_token_edit.setEnabled(True)
        self.crm_token_edit.clear()
        self.crm_token_edit.setFocus()

    def current_config(self) -> PersistentDesktopConfig:
        values = self.config_store.load().model_dump(mode="python")
        values.update(
            {
                "agent_name": self.agent_name_edit.text().strip(),
                "crm_ws_url": self.crm_url_edit.text().strip() or None,
                "smart_pos_host": self.smart_pos_host_edit.text().strip() or None,
                "smart_pos_port": self.smart_pos_port_spin.value(),
                "smart_pos_client_name": self.client_name_edit.text().strip(),
                "smart_pos_tls_mode": self.tls_mode_combo.currentText(),
                "smart_pos_ca_bundle": self.ca_bundle_edit.text().strip() or None,
                "start_minimized": self.start_minimized_check.isChecked(),
            }
        )
        return PersistentDesktopConfig.model_validate(values)

    def save(self) -> bool:
        try:
            config = self.current_config()
            if not config.is_complete():
                raise ValueError("Заполните название агента, CRM URL и IP Smart POS.")
            Settings.model_validate(config.as_settings_values())
            if self._token_replacement_requested:
                token = self.crm_token_edit.text().strip()
                if not token:
                    raise ValueError("Введите CRM Agent Token.")
                self.secret_store.set("crm_agent_token", token)
            self.config_store.save(config)
            self._apply_autostart(self.autostart_check.isChecked())
        except (OSError, RuntimeError, ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Настройки не сохранены", str(exc))
            return False
        self.configuration_saved.emit()
        self.accept()
        return True

    @staticmethod
    def _apply_autostart(enabled: bool) -> None:
        if enabled:
            autostart.enable(autostart.current_gui_executable())
        else:
            autostart.disable()

    def selected_ca_bundle(self) -> Path | None:
        value = self.ca_bundle_edit.text().strip()
        return Path(value) if value else None
