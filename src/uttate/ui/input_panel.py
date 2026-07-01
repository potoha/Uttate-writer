from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class RoughInputEdit(QPlainTextEdit):
    """Rough-input editor with IME-like keys reassigned to app operations."""

    commit_requested = Signal(str)
    escape_on_empty_requested = Signal()
    mode_toggle_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API name
        if event.key() == Qt.Key.Key_F2:
            self.mode_toggle_requested.emit()
            event.accept()
            return

        if event.key() == Qt.Key.Key_Escape:
            if self.toPlainText():
                self.clear()
            else:
                self.escape_on_empty_requested.emit()
            event.accept()
            return

        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return

            raw_text = self.toPlainText()
            if raw_text.strip():
                self.clear()
                self.commit_requested.emit(raw_text)
            event.accept()
            return

        if event.key() == Qt.Key.Key_Space:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.insertPlainText(" ")
            else:
                self.insertPlainText(" | ")
            event.accept()
            return

        super().keyPressEvent(event)


class InputPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = RoughInputEdit()
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
