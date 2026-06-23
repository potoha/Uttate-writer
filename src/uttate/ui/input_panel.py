from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class RoughInputEdit(QPlainTextEdit):
    """Rough-input editor where Enter commits and Shift+Enter inserts a newline."""

    commit_requested = Signal(str)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API name
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
        super().keyPressEvent(event)


class InputPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = RoughInputEdit()
        self.editor.setObjectName("roughInputEditor")
        self.editor.setPlaceholderText(
            "ラフなローマ字・日本語・Englishをそのまま入力…\nEnterで送信 / Shift+Enterで改行"
        )
        self.editor.setMinimumHeight(150)

        title = QLabel("Input Mode")
        title.setObjectName("sectionTitle")
        hint = QLabel("変換を待たず、次のチャンクを書き続けられます。")
        hint.setObjectName("sectionHint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.editor)
