from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from uttate.keymap import DEFAULT_BINDINGS, KeyConfig, key_sequence_from_event

MODE_LABELS = {
    "global": "Global",
    "input": "Input",
    "review": "Review",
    "candidate_edit": "Candidate edit",
}


class KeyCaptureDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Press shortcut")
        self.setModal(True)
        self.sequence: str | None = None

        layout = QVBoxLayout(self)
        label = QLabel("Press a key or combination")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API name
        sequence = key_sequence_from_event(event)
        if sequence is None:
            return
        self.sequence = sequence
        event.accept()
        self.accept()


class SettingsWindow(QDialog):
    key_config_saved = Signal(KeyConfig)

    def __init__(self, key_config: KeyConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Uttate Settings")
        self.resize(780, 460)
        self.key_config = key_config

        self.mode_buttons: dict[str, QPushButton] = {}
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Action", "Key", "Role", "Note"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.change_button = QPushButton("Change key")
        self.clear_button = QPushButton("Clear key")
        self.reset_button = QPushButton("Reset selected")
        self.reset_all_button = QPushButton("Reset all")
        self.save_button = QPushButton("Save")

        self.current_mode = "global"
        self._build_layout()
        self._connect_signals()
        self._select_mode("global")

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)

        mode_bar = QHBoxLayout()
        for mode, label in MODE_LABELS.items():
            button = QPushButton(label)
            button.setCheckable(True)
            self.mode_buttons[mode] = button
            mode_bar.addWidget(button)
        mode_bar.addStretch(1)
        layout.addLayout(mode_bar)

        layout.addWidget(self.table, 1)

        action_bar = QHBoxLayout()
        action_bar.addWidget(self.change_button)
        action_bar.addWidget(self.clear_button)
        action_bar.addWidget(self.reset_button)
        action_bar.addWidget(self.reset_all_button)
        action_bar.addStretch(1)
        action_bar.addWidget(self.save_button)
        layout.addLayout(action_bar)

    def _connect_signals(self) -> None:
        for mode, button in self.mode_buttons.items():
            button.clicked.connect(
                lambda _checked=False, selected_mode=mode: self._select_mode(selected_mode)
            )
        self.change_button.clicked.connect(self._change_selected_key)
        self.clear_button.clicked.connect(self._clear_selected_key)
        self.reset_button.clicked.connect(self._reset_selected)
        self.reset_all_button.clicked.connect(self._reset_all)
        self.save_button.clicked.connect(self._save)

    def _select_mode(self, mode: str) -> None:
        self.current_mode = mode
        for mode_name, button in self.mode_buttons.items():
            button.setChecked(mode_name == mode)
        self._populate_table()

    def _populate_table(self) -> None:
        bindings = self.key_config.bindings(self.current_mode)
        self.table.setRowCount(len(bindings))
        for row, binding in enumerate(bindings):
            action_item = QTableWidgetItem(binding.label)
            action_item.setData(Qt.ItemDataRole.UserRole, binding.action)
            self.table.setItem(row, 0, action_item)
            self.table.setItem(row, 1, QTableWidgetItem(", ".join(binding.keys) or "(none)"))
            self.table.setItem(row, 2, QTableWidgetItem(binding.role))
            self.table.setItem(row, 3, QTableWidgetItem(binding.note))
        if bindings:
            self.table.selectRow(0)

    def _selected_action(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        action = item.data(Qt.ItemDataRole.UserRole)
        return action if isinstance(action, str) else None

    def _change_selected_key(self) -> None:
        action = self._selected_action()
        if action is None:
            return
        dialog = KeyCaptureDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.sequence is None:
            return
        self.key_config.set_keys(self.current_mode, action, (dialog.sequence,))
        self._populate_table()

    def _clear_selected_key(self) -> None:
        action = self._selected_action()
        if action is None:
            return
        self.key_config.set_keys(self.current_mode, action, ())
        self._populate_table()

    def _reset_selected(self) -> None:
        action = self._selected_action()
        if action is None:
            return
        defaults = KeyConfig(DEFAULT_BINDINGS)
        self.key_config.set_keys(
            self.current_mode,
            action,
            defaults.keys_for(self.current_mode, action),
        )
        self._populate_table()

    def _reset_all(self) -> None:
        self.key_config = KeyConfig(DEFAULT_BINDINGS)
        self._populate_table()

    def _save(self) -> None:
        conflicts = self.key_config.find_conflicts()
        if conflicts:
            message = "Some shortcuts are assigned more than once:\n\n" + "\n".join(conflicts[:8])
            if len(conflicts) > 8:
                message += "\n..."
            response = QMessageBox.warning(
                self,
                "Shortcut conflicts",
                message,
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            )
            if response != QMessageBox.StandardButton.Save:
                return
        self.key_config.save()
        self.key_config_saved.emit(self.key_config)
        self.accept()
