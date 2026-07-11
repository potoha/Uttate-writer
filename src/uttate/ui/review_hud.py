from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from uttate.config import ReviewHUDSettings
from uttate.models import Chunk, ChunkStatus


class ReviewHUD(QWidget):
    """Compact heads-up review surface for actionable conversion chunks."""

    always_show_changed = Signal(bool)

    def __init__(self, settings: ReviewHUDSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("review-hud")
        self.settings = settings
        self._chunk_lookup: Callable[[str], Chunk] | None = None
        self._chunk_ids: list[str] = []
        self._selected_chunk_id: str | None = None
        self._candidate_indexes: dict[str, int] = {}
        self._editing_chunk_id: str | None = None
        self.setFixedSize(settings.width, settings.height)

        self.summary_label = QLabel("pending 0")
        self.summary_label.setObjectName("reviewHudSummary")
        self.always_show_checkbox = QCheckBox("Always show")
        self.always_show_checkbox.setObjectName("reviewHudAlwaysShow")
        self.always_show_checkbox.setChecked(settings.always_show)
        self.queue = QListWidget()
        self.queue.setObjectName("queue-item")
        self.queue.setMaximumHeight(92)
        self.queue.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.status_label = QLabel("status: none")
        self.status_label.setObjectName("reviewHudStatus")
        self.meta_label = QLabel("provider / model")
        self.meta_label.setObjectName("reviewHudMeta")
        self.preview_text = QPlainTextEdit()
        self.preview_text.setObjectName("preview-text")
        self.preview_text.setProperty("class", "preview-text")
        self.preview_text.setReadOnly(True)
        self.original_text = QPlainTextEdit()
        self.original_text.setObjectName("original-text")
        self.original_text.setReadOnly(True)
        self.diff_text = QPlainTextEdit()
        self.diff_text.setObjectName("diff-text")
        self.diff_text.setReadOnly(True)
        self.shortcut_bar = QLabel("↑/↓ select  Enter accept  F edit  R resend  Esc close")
        self.shortcut_bar.setObjectName("shortcut-bar")
        self.shortcut_bar.setProperty("class", "shortcut-bar")

        details = QFrame()
        details.setObjectName("reviewHudDetails")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(4)
        details_layout.addWidget(self.status_label)
        details_layout.addWidget(self.meta_label)
        details_layout.addWidget(self.preview_text, 1)
        details_layout.addWidget(self.original_text)
        details_layout.addWidget(self.diff_text)

        header = QHBoxLayout()
        header.addWidget(QLabel("Review"))
        header.addWidget(self.always_show_checkbox)
        header.addStretch(1)
        header.addWidget(self.summary_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.queue)
        layout.addWidget(details, 1)
        layout.addWidget(self.shortcut_bar)

        self.queue.currentRowChanged.connect(self._select_visible_row)
        self.always_show_checkbox.toggled.connect(self.always_show_changed.emit)
        self._apply_optional_visibility()

    def set_settings(self, settings: ReviewHUDSettings) -> None:
        self.settings = settings
        self.always_show_checkbox.blockSignals(True)
        self.always_show_checkbox.setChecked(settings.always_show)
        self.always_show_checkbox.blockSignals(False)
        self.setFixedSize(settings.width, settings.height)
        self._apply_optional_visibility()
        self.refresh()

    def set_chunks(
        self,
        chunk_ids: list[str],
        chunk_lookup: Callable[[str], Chunk],
        *,
        selected_chunk_id: str | None = None,
        editing_chunk_id: str | None = None,
    ) -> None:
        self._chunk_ids = chunk_ids
        self._chunk_lookup = chunk_lookup
        self._editing_chunk_id = editing_chunk_id
        if selected_chunk_id is not None:
            self._selected_chunk_id = selected_chunk_id
        elif self._selected_chunk_id not in self._chunk_ids:
            self._selected_chunk_id = self._chunk_ids[0] if self._chunk_ids else None
        self.refresh()

    def selected_chunk_id(self) -> str | None:
        return self._selected_chunk_id

    def candidate_index(self, chunk_id: str) -> int:
        return self._candidate_indexes.get(chunk_id, 0)

    def set_candidate_index(self, chunk_id: str, index: int) -> None:
        self._candidate_indexes[chunk_id] = 1 if index == 1 else 0
        self.refresh()

    def refresh(self) -> None:
        self.queue.blockSignals(True)
        self.queue.clear()
        visible_ids = self._visible_chunk_ids()
        for chunk_id in visible_ids:
            chunk = self._lookup(chunk_id)
            item = QListWidgetItem(_queue_text(chunk, self.candidate_index(chunk.id)))
            item.setData(Qt.ItemDataRole.UserRole, chunk.id)
            item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, _item_class(chunk, chunk.id))
            item.setToolTip(_queue_tooltip(chunk))
            self.queue.addItem(item)

        selected_row = (
            visible_ids.index(self._selected_chunk_id)
            if self._selected_chunk_id in visible_ids
            else -1
        )
        self.queue.setCurrentRow(selected_row)
        self.queue.blockSignals(False)
        self._render_details()

    def _visible_chunk_ids(self) -> list[str]:
        return self._chunk_ids[: self.settings.visible_pending_count]

    def _select_visible_row(self, row: int) -> None:
        if row < 0:
            return
        item = self.queue.item(row)
        if item is None:
            return
        value = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, str):
            self._selected_chunk_id = value
            self._render_details()

    def _render_details(self) -> None:
        selected = self._selected_chunk()
        total = len(self._chunk_ids)
        if selected is None:
            self.summary_label.setText("pending 0")
            self.status_label.setText("status: none")
            self.meta_label.setText("")
            self.preview_text.setPlainText("No pending chunks")
            self.original_text.setPlainText("")
            self.diff_text.setPlainText("")
            return

        selected_index = (
            self._chunk_ids.index(selected.id) + 1
            if selected.id in self._chunk_ids
            else 0
        )
        self.summary_label.setText(f"pending {total} / selected {selected_index}")
        is_editing = selected.id == self._editing_chunk_id
        self.status_label.setText(f"status: {_display_state(selected, is_editing)}")
        provider = selected.provider or "provider: unknown"
        model = selected.model or "model: unknown"
        self.meta_label.setText(f"{provider} / {model}")
        selected_text = selected_candidate_text(selected, self.candidate_index(selected.id))
        self.preview_text.setPlainText(selected_text)
        self.original_text.setPlainText(selected.raw_text)
        self.diff_text.setPlainText(_simple_diff(selected.raw_text, selected_text))

    def _selected_chunk(self) -> Chunk | None:
        if self._selected_chunk_id is None:
            return None
        try:
            return self._lookup(self._selected_chunk_id)
        except KeyError:
            return None

    def _lookup(self, chunk_id: str) -> Chunk:
        if self._chunk_lookup is None:
            raise KeyError(chunk_id)
        return self._chunk_lookup(chunk_id)

    def _apply_optional_visibility(self) -> None:
        self.original_text.setVisible(self.settings.show_original)
        self.diff_text.setVisible(self.settings.show_diff)


def selected_candidate_text(chunk: Chunk, candidate_index: int) -> str:
    if candidate_index == 1 and chunk.candidate_2:
        return chunk.candidate_2
    return chunk.candidate_1 or chunk.adopted_text or chunk.raw_text


def is_hud_chunk(
    chunk: Chunk,
    *,
    auto_remove_accepted: bool,
    editing_chunk_id: str | None,
) -> bool:
    if chunk.id == editing_chunk_id:
        return True
    if chunk.status in {
        ChunkStatus.READY_FOR_REVIEW,
        ChunkStatus.EDITED,
        ChunkStatus.FAILED,
        ChunkStatus.QUEUED,
        ChunkStatus.CONVERTING,
    }:
        return True
    return chunk.status == ChunkStatus.ADOPTED and not auto_remove_accepted


def _queue_text(chunk: Chunk, candidate_index: int) -> str:
    status = _display_state(chunk, False)
    preview = selected_candidate_text(chunk, candidate_index)
    preview = " ".join(preview.split())
    if len(preview) > 64:
        preview = f"{preview[:61]}..."
    return f"{status}\n{preview}"


def _queue_tooltip(chunk: Chunk) -> str:
    lines = [f"status: {chunk.status.value}", f"raw: {chunk.raw_text}"]
    if chunk.provider:
        lines.append(f"provider: {chunk.provider}")
    if chunk.model:
        lines.append(f"model: {chunk.model}")
    if chunk.error_message:
        lines.append(f"error: {chunk.error_message}")
    return "\n".join(lines)


def _display_state(chunk: Chunk, is_editing: bool) -> str:
    if is_editing:
        return "editing"
    if chunk.status in {ChunkStatus.QUEUED, ChunkStatus.CONVERTING}:
        return "resending"
    if chunk.status in {ChunkStatus.READY_FOR_REVIEW, ChunkStatus.EDITED}:
        return "pending_review"
    if chunk.status == ChunkStatus.ADOPTED:
        return "accepted"
    if chunk.status == ChunkStatus.FAILED:
        return "error"
    return chunk.status.value


def _item_class(chunk: Chunk, chunk_id: str) -> str:
    classes = ["queue-item"]
    if chunk.status == ChunkStatus.ADOPTED:
        classes.append("queue-item-accepted")
    elif chunk.status == ChunkStatus.FAILED:
        classes.append("queue-item-error")
    else:
        classes.append("queue-item-pending")
    if chunk.id == chunk_id:
        classes.append("queue-item-selected")
    return " ".join(classes)


def _simple_diff(original: str, converted: str) -> str:
    if original == converted:
        return "no difference"
    return f"- {original}\n+ {converted}"
