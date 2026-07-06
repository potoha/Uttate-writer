from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from uttate.config import ProviderSettings

PROVIDER_LABELS: dict[str, str] = {
    "local_ai": "Local AI",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
}


class ProviderPanel(QWidget):
    """Small, portable provider switcher.

    This widget intentionally knows nothing about queues, chunks, or windows. It only
    presents provider/model state and emits the selected provider id, so it can move to
    main or another shell without bringing the current MainWindow along.
    """

    provider_change_requested = Signal(str)
    settings_requested = Signal()

    def __init__(self, settings: ProviderSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("providerPanel")
        self.provider_combo = QComboBox()
        for provider_type, label in PROVIDER_LABELS.items():
            self.provider_combo.addItem(label, provider_type)
        self.model_label = QLabel()
        self.model_label.setObjectName("providerModelLabel")
        self.error_label = QLabel()
        self.error_label.setObjectName("providerErrorLabel")
        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setToolTip("Open key settings")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("AI"))
        layout.addWidget(self.provider_combo)
        layout.addWidget(self.model_label, 1)
        layout.addWidget(self.error_label, 2)
        layout.addWidget(self.settings_button)

        self.provider_combo.currentIndexChanged.connect(self._emit_current_provider)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.set_settings(settings)

    def set_settings(self, settings: ProviderSettings, *, error: str = "") -> None:
        provider_type = settings.type if settings.type in PROVIDER_LABELS else "local_ai"
        index = self.provider_combo.findData(provider_type)
        if index >= 0 and self.provider_combo.currentIndex() != index:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(index)
            self.provider_combo.blockSignals(False)
        self.model_label.setText(f"Model: {_model_label(settings)}")
        self.error_label.setText(error)

    def _emit_current_provider(self) -> None:
        provider_type = self.provider_combo.currentData()
        if isinstance(provider_type, str):
            self.provider_change_requested.emit(provider_type)


def _model_label(settings: ProviderSettings) -> str:
    if settings.type == "gemini":
        return settings.gemini_model
    if settings.type == "openai":
        return settings.openai_model
    if settings.type == "local_ai":
        return settings.compatible_model or "auto-detect"
    return "local_ai"
