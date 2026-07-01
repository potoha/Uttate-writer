from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from uttate.models import Chunk, ChunkStatus


class ChunkListWidget(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("chunkList")
        self._candidate_indexes: dict[str, int] = {}
        self.setAlternatingRowColors(True)
        self.setMinimumWidth(250)
        self.setWordWrap(True)
        self.setSpacing(4)

    def add_chunk(self, chunk: Chunk) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, chunk.id)
        self._candidate_indexes[chunk.id] = 0
        self.addItem(item)
        self.update_chunk(chunk)

    def update_chunk(self, chunk: Chunk) -> None:
        item = self._item_for_chunk(chunk.id)
        if item is None:
            return
        index = self.row(item) + 1
        summary = _card_text(chunk, self.candidate_index(chunk.id))
        if len(summary) > 44:
            summary = f"{summary[:43]}…"
        status = display_status(chunk.status)
        item.setText(f"{index:02d}  [{status}]\n{summary}")
        item.setToolTip(_tooltip_text(chunk))
        item.setBackground(_status_color(chunk.status))

    def candidate_index(self, chunk_id: str) -> int:
        return self._candidate_indexes.get(chunk_id, 0)

    def set_candidate_index(self, chunk_id: str, index: int) -> None:
        self._candidate_indexes[chunk_id] = 1 if index == 1 else 0

    def selected_chunk_id(self) -> str | None:
        item = self.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    def _item_for_chunk(self, chunk_id: str) -> QListWidgetItem | None:
        for index in range(self.count()):
            item = self.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == chunk_id:
                return item
        return None


def display_status(status: ChunkStatus) -> str:
    if status in {ChunkStatus.QUEUED, ChunkStatus.CONVERTING}:
        return "processing"
    if status in {ChunkStatus.READY_FOR_REVIEW, ChunkStatus.EDITED}:
        return "pending"
    if status == ChunkStatus.ADOPTED:
        return "accepted"
    if status == ChunkStatus.REJECTED:
        return "rejected"
    if status == ChunkStatus.FAILED:
        return "error"
    return status.value


def _card_text(chunk: Chunk, candidate_index: int) -> str:
    if chunk.status == ChunkStatus.FAILED:
        return chunk.error_message or "変換に失敗しました。Rで再送できます。"
    if chunk.status == ChunkStatus.ADOPTED and chunk.adopted_text:
        return chunk.adopted_text
    if candidate_index == 1 and chunk.candidate_2:
        return chunk.candidate_2
    if chunk.candidate_1:
        return chunk.candidate_1
    return " ".join(chunk.raw_text.split())


def _tooltip_text(chunk: Chunk) -> str:
    lines = [f"raw: {chunk.raw_text}"]
    if chunk.candidate_1:
        lines.append(f"candidate A: {chunk.candidate_1}")
    if chunk.candidate_2:
        lines.append(f"candidate B: {chunk.candidate_2}")
    if chunk.error_message:
        lines.append(f"error: {chunk.error_message}")
    return "\n".join(lines)


def _status_color(status: ChunkStatus) -> QColor:
    if status in {ChunkStatus.QUEUED, ChunkStatus.CONVERTING}:
        return QColor("#e0f2fe")
    if status in {ChunkStatus.READY_FOR_REVIEW, ChunkStatus.EDITED}:
        return QColor("#fef3c7")
    if status == ChunkStatus.ADOPTED:
        return QColor("#dcfce7")
    if status == ChunkStatus.REJECTED:
        return QColor("#e5e7eb")
    if status == ChunkStatus.FAILED:
        return QColor("#fee2e2")
    return QColor("#ffffff")
