from __future__ import annotations

import json

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from uttate.models import Chunk


class ReviewPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("Review")
        title.setObjectName("sectionTitle")
        self.status_label = QLabel("チャンクを選択してください。")
        self.status_label.setObjectName("reviewStatus")
        self.raw_field = self._field("Raw")
        self.normalized_field = self._field("Normalized")
        self.candidate_1_field = self._field("Candidate A")
        self.candidate_2_field = self._field("Candidate B")
        self.uncertain_field = self._field("Uncertain")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(title)
        layout.addWidget(self.status_label)
        for label, field in (
            ("Raw", self.raw_field),
            ("Normalized", self.normalized_field),
            ("Candidate A", self.candidate_1_field),
            ("Candidate B", self.candidate_2_field),
            ("Uncertain", self.uncertain_field),
        ):
            layout.addWidget(QLabel(label))
            layout.addWidget(field)

        self.show_chunk(None)

    def show_chunk(self, chunk: Chunk | None) -> None:
        if chunk is None:
            self.status_label.setText("チャンクを選択してください。")
            values = ("", "", "", "", "")
        else:
            self.status_label.setText(f"Status: {chunk.status.value}")
            uncertainty = (
                json.dumps(chunk.uncertain, ensure_ascii=False, indent=2)
                if chunk.uncertain
                else "none"
            )
            values = (
                chunk.raw_text,
                chunk.normalized or "",
                chunk.candidate_1 or "",
                chunk.candidate_2 or "",
                uncertainty,
            )

        for field, value in zip(
            (
                self.raw_field,
                self.normalized_field,
                self.candidate_1_field,
                self.candidate_2_field,
                self.uncertain_field,
            ),
            values,
            strict=True,
        ):
            field.setPlainText(value)

    @staticmethod
    def _field(name: str) -> QPlainTextEdit:
        field = QPlainTextEdit()
        field.setObjectName(f"review{name.replace(' ', '')}")
        field.setReadOnly(True)
        field.setMaximumHeight(82)
        return field
