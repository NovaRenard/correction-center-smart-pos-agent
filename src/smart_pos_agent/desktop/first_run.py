"""First-run wizard is a constrained settings dialog with clear setup guidance."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..storage.secret_store import SecretStore
from .config_store import DesktopConfigStore
from .settings_window import SettingsWindow


class FirstRunWizard(SettingsWindow):
    def __init__(
        self,
        config_store: DesktopConfigStore,
        secret_store: SecretStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(config_store, secret_store, first_run=True, parent=parent)
        guidance = QLabel(
            "Заполните параметры CRM и Smart POS. CRM Agent Token будет сохранён "
            "в защищённом хранилище Windows и больше не будет показан."
        )
        guidance.setWordWrap(True)
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.insertWidget(0, guidance)
