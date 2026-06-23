from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from uttate.models import Chunk


class ChunkListWidget(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("chunkList")
        self.setAlternatingRowColors(True)
        self.setMinimumWidth(250)

    def add_chunk(self, chunk: Chunk) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, chunk.id)
        self.addItem(item)
        self.update_chunk(chunk)

    def update_chunk(self, chunk: Chunk) -> None:
        item = self._item_for_chunk(chunk.id)
        if item is None:
            return
        index = self.row(item) + 1
        summary = " ".join(chunk.raw_text.split())
        if len(summary) > 44:
            summary = f"{summary[:43]}…"
        item.setText(f"{index:02d}  {chunk.status.value}\n{summary}")
        item.setToolTip(chunk.raw_text)

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
