from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from uttate.config import InputPanelSettings, ProviderSettings
from uttate.keymap import KeyConfig
from uttate.ui.provider_panel import PROVIDER_LABELS


class RoughInputEdit(QPlainTextEdit):
    """Rough-input editor with IME-like keys reassigned to app operations."""

    commit_requested = Signal(str)
    send_requested = Signal(str)
    escape_on_empty_requested = Signal()
    mode_toggle_requested = Signal()

    def __init__(self, key_config: KeyConfig | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key_config = key_config or KeyConfig()

    def set_key_config(self, key_config: KeyConfig) -> None:
        self.key_config = key_config

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API name
        action = self.key_config.action_for("input", event)
        if action == "clear_or_hide":
            if self.toPlainText():
                self.clear()
            else:
                self.escape_on_empty_requested.emit()
            event.accept()
            return

        if action == "insert_newline":
            super().keyPressEvent(event)
            return

        if action == "send_or_convert":
            raw_text = self.toPlainText()
            if raw_text.strip():
                self.send_requested.emit(raw_text)
            event.accept()
            return

        if action == "commit_chunk":
            raw_text = self.toPlainText()
            if raw_text.strip():
                self.clear()
                self.commit_requested.emit(raw_text)
            event.accept()
            return

        if action == "insert_space":
            self.insertPlainText(" ")
            event.accept()
            return

        if action == "insert_chunk_separator":
            self.insertPlainText(" | ")
            event.accept()
            return

        super().keyPressEvent(event)


class InputPanel(QWidget):
    provider_change_requested = Signal(str)
    settings_requested = Signal()
    send_requested = Signal()
    always_on_top_changed = Signal(bool)

    def __init__(
        self,
        key_config: KeyConfig | None = None,
        provider_settings: ProviderSettings | None = None,
        settings: InputPanelSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("input-panel")
        self.setWindowTitle("Uttate InputPanel")
        self.settings = settings or InputPanelSettings()
        self.provider_settings = provider_settings or ProviderSettings()
        self.privacy_warning_enabled = True

        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("settingsButton")
        self.always_on_top_button = QPushButton("Always on top")
        self.always_on_top_button.setObjectName("alwaysOnTopButton")
        self.always_on_top_button.setCheckable(True)
        self.always_on_top_button.setChecked(self.settings.always_on_top)
        self.always_on_top_button.setToolTip("Keep all Uttate windows in front")
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("providerSelector")
        for provider_type, label in PROVIDER_LABELS.items():
            self.provider_combo.addItem(label, provider_type)
        self.model_label = QLabel()
        self.model_label.setObjectName("providerModelLabel")

        self.title = QLabel("Input mode")
        self.title.setObjectName("sectionTitle")
        self.hint = QLabel("Enter or Ctrl+Enter: send rough input")
        self.hint.setObjectName("sectionHint")

        self.editor = RoughInputEdit(key_config)
        self.editor.setObjectName("roughInputEditor")
        self.editor.setProperty("class", "input-text")
        self.editor.setPlaceholderText(
            "ローマ字・English・記号列を入力…  Spaceで区切り / Shift+Spaceで空白"
        )
        self.editor.setMinimumHeight(64)

        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.warning = QLabel("")
        self.warning.setObjectName("inputPanelWarning")
        self.warning.setProperty("class", "privacy-warning privacy-warning-local")
        self.warning.setWordWrap(True)
        self.setFixedSize(self.settings.width, self.settings.height)

        top_row = QHBoxLayout()
        top_row.addWidget(self.settings_button)
        top_row.addWidget(self.always_on_top_button)
        top_row.addWidget(QLabel("AI"))
        top_row.addWidget(self.provider_combo)
        top_row.addWidget(self.model_label, 1)

        editor_row = QHBoxLayout()
        editor_row.addWidget(self.editor, 1)
        editor_row.addWidget(self.send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addLayout(top_row)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        layout.addLayout(editor_row, 1)
        layout.addWidget(self.warning)

        self.provider_combo.currentIndexChanged.connect(self._emit_current_provider)
        self.settings_button.clicked.connect(self.settings_requested.emit)
        self.always_on_top_button.toggled.connect(self.always_on_top_changed.emit)
        self.send_button.clicked.connect(self.send_requested.emit)
        self.set_provider_settings(self.provider_settings)

    def set_settings(self, settings: InputPanelSettings) -> None:
        self.settings = settings
        self.setFixedSize(settings.width, settings.height)
        self.always_on_top_button.blockSignals(True)
        self.always_on_top_button.setChecked(settings.always_on_top)
        self.always_on_top_button.blockSignals(False)

    def set_provider_settings(
        self,
        settings: ProviderSettings,
        *,
        error: str = "",
        show_privacy_warning: bool = True,
    ) -> None:
        del error
        self.provider_settings = settings
        self.privacy_warning_enabled = show_privacy_warning
        provider_type = settings.type if settings.type in PROVIDER_LABELS else "local_ai"
        index = self.provider_combo.findData(provider_type)
        if index >= 0 and self.provider_combo.currentIndex() != index:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(index)
            self.provider_combo.blockSignals(False)
        self.model_label.setText(_provider_model_label(settings))
        self.set_provider_warning(settings.type)

    def set_send_enabled(self, enabled: bool) -> None:
        self.send_button.setEnabled(enabled)
        if enabled:
            self.send_button.setText("Convert" if self.title.text() == "Candidate edit" else "Send")
        else:
            self.send_button.setText("Sending...")

    def set_mode_label(self, mode: str) -> None:
        if mode == "Candidate edit":
            self.title.setText("Candidate edit")
            self.hint.setText("Enter: accept / Ctrl+Enter or Convert: reconvert / Esc: cancel")
            self.send_button.setText("Convert")
        elif mode == "Review":
            self.title.setText("Review mode")
            self.hint.setText("F: edit candidate / Enter: accept / R: resend")
            self.send_button.setText("Send")
        else:
            self.title.setText("Input mode")
            self.hint.setText("Enter or Ctrl+Enter: send rough input")
            self.send_button.setText("Send")

    def set_provider_warning(self, provider_type: str) -> None:
        if not self.privacy_warning_enabled:
            self.warning.setVisible(False)
            return
        self.warning.setVisible(True)
        if provider_type == "gemini":
            self.warning.setText(
                "外部API使用中: Gemini API。"
                "個人情報・未公開原稿・秘密情報は入力しないでください。"
            )
            self._set_warning_class("privacy-warning privacy-warning-external")
        elif provider_type == "openai":
            self.warning.setText(
                "外部API使用中: OpenAI API。"
                "個人情報・未公開原稿・秘密情報は入力しないでください。"
            )
            self._set_warning_class("privacy-warning privacy-warning-external")
        elif _is_local_provider(provider_type):
            self.warning.setText("Local AI使用中: 入力は外部APIへ送信されません。")
            self._set_warning_class("privacy-warning privacy-warning-local")
        else:
            self.warning.setText(
                "外部API使用中: External API。"
                "個人情報・未公開原稿・秘密情報は入力しないでください。"
            )
            self._set_warning_class("privacy-warning privacy-warning-external")

    def _set_warning_class(self, class_name: str) -> None:
        self.warning.setProperty("class", class_name)
        style = self.warning.style()
        style.unpolish(self.warning)
        style.polish(self.warning)

    def _emit_current_provider(self) -> None:
        provider_type = self.provider_combo.currentData()
        if isinstance(provider_type, str):
            self.provider_change_requested.emit(provider_type)


def _provider_model_label(settings: ProviderSettings) -> str:
    if settings.type == "gemini":
        return f"Gemini API / {settings.gemini_model or 'model not selected'}"
    if settings.type == "openai":
        return f"OpenAI API / {settings.openai_model or 'model not selected'}"
    if settings.type == "local_ai":
        return f"Local AI / {settings.compatible_model or 'model not selected'}"
    if _is_local_provider(settings.type):
        return f"Local AI / {settings.compatible_model or 'model not selected'}"
    return f"External API / {settings.model or 'model not selected'}"


def _is_local_provider(provider_type: str) -> bool:
    return provider_type in {"local_ai", "lmstudio", "lm_studio", "compatible", "mock"}
