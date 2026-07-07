from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from uttate.config import (
    AppSettings,
    DatasetCaptureSettings,
    InputPanelSettings,
    ReviewHUDSettings,
    default_dataset_capture_path,
    save_settings,
)
from uttate.keymap import DEFAULT_BINDINGS, KeyConfig, key_sequence_from_event
from uttate.prompts.registry import PROMPT_REGISTRY_NOTICE, LocalAIPromptRegistry

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
    app_settings_saved = Signal(AppSettings)
    local_ai_prompts_saved = Signal(object)

    def __init__(
        self,
        key_config: KeyConfig,
        settings: AppSettings | None = None,
        prompt_registry: LocalAIPromptRegistry | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Uttate Settings")
        self.resize(780, 560)
        self.key_config = key_config
        self.app_settings = settings or AppSettings()
        self.prompt_registry = prompt_registry or LocalAIPromptRegistry.load()

        self.mode_buttons: dict[str, QPushButton] = {}
        self.dataset_capture_checkbox = QCheckBox("Record review accepts as dataset candidates")
        self.dataset_capture_checkbox.setChecked(self.app_settings.dataset.capture_enabled)
        self.dataset_store_path = QLineEdit(self._dataset_store_text())
        self.dataset_store_path.setPlaceholderText(str(default_dataset_capture_path()))
        self.review_pending_count = QComboBox()
        for count in (1, 3, 5):
            self.review_pending_count.addItem(str(count), count)
        pending_count_index = self.review_pending_count.findData(
            self.app_settings.review_hud.visible_pending_count
        )
        self.review_pending_count.setCurrentIndex(
            max(0, pending_count_index)
        )
        self.review_position = QComboBox()
        for value, label in (
            ("bottom_right", "Bottom right"),
            ("bottom_center", "Bottom center"),
            ("top_right", "Top right"),
        ):
            self.review_position.addItem(label, value)
        self.review_position.setCurrentIndex(
            max(0, self.review_position.findData(self.app_settings.review_hud.position))
        )
        self.review_width = self._spin_box(self.app_settings.review_hud.width, 240, 1000)
        self.review_height = self._spin_box(self.app_settings.review_hud.height, 180, 800)
        self.input_position = QComboBox()
        for value, label in (
            ("bottom_center", "Bottom center"),
            ("bottom_right", "Bottom right"),
            ("top_right", "Top right"),
        ):
            self.input_position.addItem(label, value)
        self.input_position.setCurrentIndex(
            max(0, self.input_position.findData(self.app_settings.input_panel.position))
        )
        self.input_width = self._spin_box(self.app_settings.input_panel.width, 280, 1200)
        self.input_height = self._spin_box(self.app_settings.input_panel.height, 120, 500)
        self.auto_remove_accepted = QCheckBox("Auto remove accepted chunks from ReviewHUD")
        self.auto_remove_accepted.setChecked(self.app_settings.review_hud.auto_remove_accepted)
        self.always_show_review_hud = QCheckBox("Always show ReviewHUD")
        self.always_show_review_hud.setChecked(self.app_settings.review_hud.always_show)
        self.show_original = QCheckBox("Show original text")
        self.show_original.setChecked(self.app_settings.review_hud.show_original)
        self.show_diff = QCheckBox("Show diff text")
        self.show_diff.setChecked(self.app_settings.review_hud.show_diff)
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
        self.prompt_profile_combo = QComboBox()
        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.prompt_notice = QLabel(
            "起動中に YAML を直接編集しても直ちには反映されません。"
            "F12 設定画面で適用した変更だけ直ちに反映します。"
        )
        self.prompt_notice.setWordWrap(True)
        self.prompt_notice.setObjectName("sectionHint")
        self.prompt_status_label = QLabel(PROMPT_REGISTRY_NOTICE)
        self.prompt_status_label.setWordWrap(True)
        self.prompt_status_label.setObjectName("sectionHint")
        self.prompt_close_button = QPushButton("変更せず閉じる (Escape)")
        self.prompt_apply_button = QPushButton("適用する (Ctrl+R)")
        self.prompt_apply_close_button = QPushButton("変更して閉じる (Ctrl+Enter)")

        self.current_mode = "global"
        self._build_layout()
        self._connect_signals()
        self._select_mode("global")
        self._populate_prompt_profiles()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_dataset_group())
        layout.addWidget(self._build_hud_group())
        layout.addWidget(self._build_prompt_group(), 1)

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

    def _build_dataset_group(self) -> QGroupBox:
        group = QGroupBox("Dataset capture")
        layout = QVBoxLayout(group)
        layout.addWidget(self.dataset_capture_checkbox)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Candidate store"))
        path_row.addWidget(self.dataset_store_path, 1)
        layout.addLayout(path_row)
        return group

    def _build_hud_group(self) -> QGroupBox:
        group = QGroupBox("HUD")
        layout = QVBoxLayout(group)

        review_row = QHBoxLayout()
        review_row.addWidget(QLabel("ReviewHUD pending"))
        review_row.addWidget(self.review_pending_count)
        review_row.addWidget(QLabel("position"))
        review_row.addWidget(self.review_position)
        review_row.addWidget(QLabel("width"))
        review_row.addWidget(self.review_width)
        review_row.addWidget(QLabel("height"))
        review_row.addWidget(self.review_height)
        layout.addLayout(review_row)

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("InputPanel position"))
        input_row.addWidget(self.input_position)
        input_row.addWidget(QLabel("width"))
        input_row.addWidget(self.input_width)
        input_row.addWidget(QLabel("height"))
        input_row.addWidget(self.input_height)
        layout.addLayout(input_row)

        toggle_row = QHBoxLayout()
        toggle_row.addWidget(self.always_show_review_hud)
        toggle_row.addWidget(self.auto_remove_accepted)
        toggle_row.addWidget(self.show_original)
        toggle_row.addWidget(self.show_diff)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)
        return group

    def _build_prompt_group(self) -> QGroupBox:
        group = QGroupBox("Local-AI prompt")
        layout = QVBoxLayout(group)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile"))
        profile_row.addWidget(self.prompt_profile_combo, 1)
        layout.addLayout(profile_row)
        layout.addWidget(self.prompt_editor, 1)
        layout.addWidget(self.prompt_notice)
        layout.addWidget(self.prompt_status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.prompt_close_button)
        button_row.addWidget(self.prompt_apply_button)
        button_row.addWidget(self.prompt_apply_close_button)
        layout.addLayout(button_row)
        return group

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
        self.prompt_profile_combo.currentIndexChanged.connect(self._load_selected_prompt_profile)
        self.prompt_close_button.clicked.connect(self.reject)
        self.prompt_apply_button.clicked.connect(self._apply_prompt_changes)
        self.prompt_apply_close_button.clicked.connect(self._apply_prompt_changes_and_close)
        self.prompt_close_button.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self.prompt_apply_button.setShortcut(QKeySequence("Ctrl+R"))
        self.prompt_apply_close_button.setShortcut(QKeySequence("Ctrl+Return"))
        QShortcut(QKeySequence("Ctrl+Enter"), self).activated.connect(
            self._apply_prompt_changes_and_close
        )

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

    def _populate_prompt_profiles(self) -> None:
        self.prompt_profile_combo.blockSignals(True)
        self.prompt_profile_combo.clear()
        for name in self.prompt_registry.profile_names():
            profile = self.prompt_registry.profile(name)
            label = name if not profile.model else f"{name} ({profile.model})"
            self.prompt_profile_combo.addItem(label, name)
        self.prompt_profile_combo.blockSignals(False)
        if self.prompt_profile_combo.count():
            self.prompt_profile_combo.setCurrentIndex(0)
            self._load_selected_prompt_profile()

    def _load_selected_prompt_profile(self) -> None:
        profile_name = self._selected_prompt_profile_name()
        if profile_name is None:
            self.prompt_editor.clear()
            return
        self.prompt_editor.setPlainText(self.prompt_registry.profile(profile_name).prompt)
        self.prompt_status_label.setText(f"Editing {profile_name}: {self.prompt_registry.path}")

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

    def _apply_prompt_changes(self) -> bool:
        profile_name = self._selected_prompt_profile_name()
        if profile_name is None:
            return False
        try:
            self.prompt_registry.set_prompt(profile_name, self.prompt_editor.toPlainText())
            self.prompt_registry.save()
        except (KeyError, OSError) as error:
            QMessageBox.critical(self, "Prompt save failed", str(error))
            return False
        self.local_ai_prompts_saved.emit(self.prompt_registry)
        self.prompt_status_label.setText(f"Saved {profile_name}: {self.prompt_registry.path}")
        return True

    def _apply_prompt_changes_and_close(self) -> None:
        if self._apply_prompt_changes():
            self.accept()

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
        self.app_settings = replace(
            self.app_settings,
            dataset=DatasetCaptureSettings(
                capture_enabled=self.dataset_capture_checkbox.isChecked(),
                capture_store_path=self.dataset_store_path.text().strip(),
            ),
            review_hud=ReviewHUDSettings(
                visible_pending_count=int(self.review_pending_count.currentData()),
                position=str(self.review_position.currentData()),
                width=self.review_width.value(),
                height=self.review_height.value(),
                auto_remove_accepted=self.auto_remove_accepted.isChecked(),
                show_original=self.show_original.isChecked(),
                show_diff=self.show_diff.isChecked(),
                always_show=self.always_show_review_hud.isChecked(),
            ),
            input_panel=InputPanelSettings(
                position=str(self.input_position.currentData()),
                width=self.input_width.value(),
                height=self.input_height.value(),
            ),
        )
        try:
            save_settings(self.app_settings)
        except OSError as error:
            QMessageBox.critical(self, "Settings save failed", str(error))
            return
        self.key_config.save()
        self.key_config_saved.emit(self.key_config)
        self.app_settings_saved.emit(self.app_settings)
        self.accept()

    def _dataset_store_text(self) -> str:
        return self.app_settings.dataset.capture_store_path or str(default_dataset_capture_path())

    def _selected_prompt_profile_name(self) -> str | None:
        profile_name = self.prompt_profile_combo.currentData()
        return profile_name if isinstance(profile_name, str) else None

    @staticmethod
    def _spin_box(value: int, minimum: int, maximum: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setValue(value)
        return box
