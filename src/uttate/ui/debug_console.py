from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from uttate.ui.chunk_list import ChunkListWidget
from uttate.ui.provider_panel import ProviderPanel
from uttate.ui.review_panel import ReviewPanel


class DebugConsole(QWidget):
    """Full diagnostic console kept out of the normal writing path."""

    def __init__(
        self,
        provider_panel: ProviderPanel,
        chunk_list: ChunkListWidget,
        review_panel: ReviewPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("debug-console")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(provider_panel)
        layout.addWidget(chunk_list, 1)
        layout.addWidget(review_panel, 2)
