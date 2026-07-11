from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QKeyEvent, QMouseEvent, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from uttate.addons.dataset_collection import (
    EXPORT_INPUT_FIELDS,
    EXPORT_TARGET_FIELDS,
    REDACTABLE_FIELDS,
    REDACTION_TYPES,
    DatasetItem,
)

REDACTION_SHORTCUTS: dict[int, str] = {
    Qt.Key.Key_1: "PERSON",
    Qt.Key.Key_2: "PLACE",
    Qt.Key.Key_3: "ORG",
    Qt.Key.Key_4: "DATE",
    Qt.Key.Key_5: "CONTACT",
    Qt.Key.Key_6: "WORK",
    Qt.Key.Key_7: "MASK",
    Qt.Key.Key_8: "CUSTOM",
}
REDACTION_MENU_TYPES: tuple[str, ...] = (
    "PERSON",
    "PLACE",
    "ORG",
    "DATE",
    "CONTACT",
    "WORK",
    "MASK",
    "CUSTOM",
)


class DatasetReviewWindow(QWidget):
    """Independent review surface for opt-in dataset candidates."""

    status_changed = Signal(str, str)
    field_safety_changed = Signal(str, str, str)
    redaction_requested = Signal(str, str, int, int, str, object)
    undo_redaction_requested = Signal(str)
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dataset-review-window")
        self.setWindowTitle("Uttate DatasetReviewWindow")
        self.resize(760, 620)
        self._items: list[DatasetItem] = []
        self._card_widgets: dict[str, QFrame] = {}
        self._editors: dict[tuple[str, str], RedactableTextEdit] = {}
        self._safety_checkboxes: dict[tuple[str, str], QCheckBox] = {}

        self.summary_label = QLabel("No dataset candidates")
        self.summary_label.setObjectName("datasetReviewSummary")
        self.summary_label.setWordWrap(True)
        self.export_button = QPushButton("Export dataset")
        self.export_button.setObjectName("datasetExportButton")

        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(8)
        self.card_layout.addStretch(1)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.card_container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        top_row = QHBoxLayout()
        top_row.addWidget(self.summary_label, 1)
        top_row.addWidget(self.export_button)
        layout.addLayout(top_row)
        layout.addWidget(scroll_area, 1)
        self.export_button.clicked.connect(self.export_requested.emit)

    def set_items(self, items: Sequence[DatasetItem]) -> None:
        self._items = list(items)
        self._render()

    def item_count(self) -> int:
        return len(self._items)

    def _render(self) -> None:
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._card_widgets.clear()
        self._editors.clear()
        self._safety_checkboxes.clear()

        if not self._items:
            self.summary_label.setText("No pending dataset candidates")
            empty = QLabel("Dataset Collection Mode is ON, but there are no accepted items yet.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.card_layout.addWidget(empty, 1)
            return

        whitelisted = sum(1 for item in self._items if item.get("dataset_status") == "whitelisted")
        self.summary_label.setText(f"dataset items {len(self._items)} / whitelisted {whitelisted}")
        for item in self._items:
            card = self._build_card(item)
            self._card_widgets[item["id"]] = card
            self.card_layout.addWidget(card)
        self.card_layout.addStretch(1)

    def _build_card(self, item: DatasetItem) -> QFrame:
        card = QFrame()
        card.setObjectName("dataset-card")
        card.setProperty("class", f"dataset-card dataset-{item.get('dataset_status', 'candidate')}")
        card.setFrameShape(QFrame.Shape.StyledPanel)

        whitelist = QCheckBox("whitelist")
        whitelist.setObjectName("datasetWhitelistCheckbox")
        whitelist.setChecked(item.get("dataset_status") == "whitelisted")
        whitelist.toggled.connect(
            lambda checked, item_id=item["id"]: self.status_changed.emit(
                item_id,
                "whitelisted" if checked else "candidate",
            )
        )

        reject_button = QPushButton("Reject")
        reject_button.setObjectName("datasetRejectButton")
        reject_button.clicked.connect(
            lambda _checked=False, item_id=item["id"]: self.status_changed.emit(item_id, "rejected")
        )

        title = QLabel(
            f"{item['id']}  status: {item.get('status', '')}  "
            f"dataset: {item.get('dataset_status', '')}"
        )
        title.setObjectName("datasetCardTitle")
        title.setWordWrap(True)

        badge_text = "External API" if item.get("external_api") else "Local"
        badge = QLabel(badge_text)
        badge.setObjectName("datasetExternalApiBadge")

        meta = QLabel(
            " / ".join(
                part
                for part in (
                    item.get("provider", "provider unknown"),
                    item.get("model", "model unknown"),
                    item.get("created_at", ""),
                    f"redactions: {len(item.get('redactions', []))}",
                )
                if part
            )
        )
        meta.setObjectName("datasetCardMeta")
        meta.setWordWrap(True)

        header = QHBoxLayout()
        header.addWidget(whitelist)
        header.addWidget(title, 1)
        header.addWidget(badge)
        header.addWidget(reject_button)

        layout = QVBoxLayout(card)
        layout.addLayout(header)
        layout.addWidget(meta)
        exported_fields = _export_source_fields(item)
        for label, key in (
            ("raw_input", "raw_input"),
            ("normalized_input", "normalized_input"),
            ("converted_text", "converted_text"),
            ("edited_text", "edited_text"),
            ("accepted_text", "accepted_text"),
        ):
            editor = RedactableTextEdit(item["id"], key, parent=self)
            editor.redaction_type_selected.connect(self._request_redaction)
            editor.undo_requested.connect(self.undo_redaction_requested.emit)
            self._editors[(item["id"], key)] = editor
            safety_checkbox = None
            if key in exported_fields:
                safety_checkbox = self._build_safety_checkbox(item, key)
                self._safety_checkboxes[(item["id"], key)] = safety_checkbox
            layout.addWidget(
                _field(
                    label,
                    str(item.get(key, "")),
                    editor,
                    safety_checkbox=safety_checkbox,
                    exported=key in exported_fields,
                )
            )
        return card

    def editor_for(self, item_id: str, field: str) -> QPlainTextEdit | None:
        return self._editors.get((item_id, field))

    def safety_checkbox_for(self, item_id: str, field: str) -> QCheckBox | None:
        """Return the explicit safety control for a field included in export."""

        return self._safety_checkboxes.get((item_id, field))

    def _build_safety_checkbox(self, item: DatasetItem, field: str) -> QCheckBox:
        safety = str(item.get("field_safety", {}).get(field, "unreviewed"))
        checkbox = QCheckBox("confirmed safe")
        checkbox.setObjectName("datasetFieldSafetyCheckbox")
        checkbox.setProperty("datasetItemId", item["id"])
        checkbox.setProperty("datasetField", field)
        checkbox.setChecked(safety in {"confirmed", "redacted"})
        if safety == "redacted":
            checkbox.setText("fully redacted")
            checkbox.setEnabled(False)
            checkbox.setToolTip("Safety is verified by the recorded anonymization.")
        else:
            checkbox.setToolTip(
                "Confirm that this exported field has no identifying or sensitive content."
            )
            checkbox.toggled.connect(
                lambda checked, item_id=item["id"], target_field=field: (
                    self.field_safety_changed.emit(
                        item_id,
                        target_field,
                        "confirmed" if checked else "unreviewed",
                    )
                )
            )
        return checkbox

    def _request_redaction(
        self,
        item_id: str,
        target_field: str,
        start: int,
        end: int,
        redaction_type: str,
    ) -> None:
        if redaction_type not in REDACTION_TYPES:
            return
        item = self._item_by_id(item_id)
        if item is None:
            return
        original_text = str(item.get(target_field, ""))[start:end]
        if not original_text:
            return

        confirmed_fields = self._confirmed_ambiguous_fields(item, target_field, original_text)
        self.redaction_requested.emit(
            item_id,
            target_field,
            start,
            end,
            redaction_type,
            confirmed_fields,
        )

    def _confirmed_ambiguous_fields(
        self,
        item: DatasetItem,
        target_field: str,
        original_text: str,
    ) -> list[str]:
        ambiguous_fields = []
        for field in REDACTABLE_FIELDS:
            if field == target_field:
                continue
            if str(item.get(field, "")).count(original_text) > 1:
                ambiguous_fields.append(field)
        if not ambiguous_fields:
            return []

        response = QMessageBox.question(
            self,
            "Confirm anonymization",
            "The selected text appears multiple times in "
            f"{', '.join(ambiguous_fields)}. Replace all exact matches there too?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return ambiguous_fields if response == QMessageBox.StandardButton.Yes else []

    def _item_by_id(self, item_id: str) -> DatasetItem | None:
        for item in self._items:
            if item.get("id") == item_id:
                return item
        return None


class RedactableTextEdit(QPlainTextEdit):
    redaction_type_selected = Signal(str, str, int, int, str)
    undo_requested = Signal(str)

    def __init__(self, item_id: str, field: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item_id = item_id
        self.field = field
        self._active_menu: QMenu | None = None
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API name
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo_requested.emit(self.item_id)
                event.accept()
                return
            redaction_type = REDACTION_SHORTCUTS.get(event.key())
            if redaction_type is not None and self.textCursor().hasSelection():
                self._emit_redaction(redaction_type)
                event.accept()
                return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.textCursor().hasSelection():
            self._show_redaction_menu(event.globalPosition().toPoint(), popup=True)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802 - Qt API name
        if self.textCursor().hasSelection():
            self._show_redaction_menu(event.globalPos(), popup=False)
            event.accept()
            return
        super().contextMenuEvent(event)

    def _show_redaction_menu(self, global_position, *, popup: bool) -> None:
        menu = QMenu(self)
        menu.setObjectName("datasetRedactionMenu")
        for redaction_type in REDACTION_MENU_TYPES:
            action = menu.addAction(redaction_type)
            action.triggered.connect(
                lambda _checked=False, selected_type=redaction_type: self._emit_redaction(
                    selected_type
                )
            )
        self._active_menu = menu
        if popup:
            menu.popup(global_position)
        else:
            menu.exec(global_position)

    def _emit_redaction(self, redaction_type: str) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return
        start = min(cursor.selectionStart(), cursor.selectionEnd())
        end = max(cursor.selectionStart(), cursor.selectionEnd())
        self.redaction_type_selected.emit(
            self.item_id,
            self.field,
            start,
            end,
            redaction_type,
        )


def _export_source_fields(item: DatasetItem) -> tuple[str, ...]:
    target_field = next(
        (field for field in EXPORT_TARGET_FIELDS if str(item.get(field, "")).strip()),
        "converted_text",
    )
    return (*EXPORT_INPUT_FIELDS, target_field)


def _field(
    label: str,
    text: str,
    editor: RedactableTextEdit,
    *,
    safety_checkbox: QCheckBox | None = None,
    exported: bool = False,
) -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    title = QLabel(f"{label} (exported)" if exported else label)
    title.setObjectName("datasetFieldLabel")
    editor.setObjectName(f"dataset-{label}")
    editor.setProperty("class", "dataset-redactable-text")
    editor.setPlainText(text)
    editor.moveCursor(QTextCursor.MoveOperation.Start)
    editor.setMaximumHeight(72)
    title_row = QHBoxLayout()
    title_row.addWidget(title)
    if safety_checkbox is not None:
        title_row.addStretch(1)
        title_row.addWidget(safety_checkbox)
    layout.addLayout(title_row)
    layout.addWidget(editor)
    return wrapper
