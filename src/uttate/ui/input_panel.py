from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from uttate.keymap import KeyConfig


class RoughInputEdit(QPlainTextEdit):
    """Rough-input editor with IME-like keys reassigned to app operations."""

    commit_requested = Signal(str)
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
    def __init__(self, key_config: KeyConfig | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = RoughInputEdit(key_config)
        self.editor.setObjectName("roughInputEditor")
        self.editor.setPlaceholderText(
            "ローマ字・English・記号列を入力…  Spaceで区切り / Shift+Spaceで空白"
        )
        self.editor.setMinimumHeight(64)
        self.editor.setMaximumHeight(96)

        self.title = QLabel("Input mode")
        self.title.setObjectName("sectionTitle")
        self.hint = QLabel("変換を待たず、次のチャンクを書き続けられます。")
        self.hint.setObjectName("sectionHint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        layout.addWidget(self.editor)

    def set_mode_label(self, mode: str) -> None:
        if mode == "Candidate edit":
            self.title.setText("Candidate edit")
            self.hint.setText("Enter: accept / Ctrl+Enter: reconvert / Esc: cancel")
        elif mode == "Review":
            self.title.setText("Review mode")
            self.hint.setText("F: edit candidate / Enter: accept / R: resend")
        else:
            self.title.setText("Input mode")
            self.hint.setText("変換を待たず、次のチャンクを書き続けられます。")
