from __future__ import annotations

import zipfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from uttate.config import (
    AppearanceSettings,
    AppSettings,
    DatasetCaptureSettings,
    GeneralSettings,
    InputPanelSettings,
    ReviewHUDSettings,
    default_dataset_history_path,
    save_settings,
)
from uttate.keymap import DEFAULT_BINDINGS, KeyConfig, key_sequence_from_event
from uttate.prompts.registry import PROMPT_REGISTRY_NOTICE, LocalAIPromptRegistry
from uttate.ui.theme import (
    BUILT_IN_THEME_IDS,
    ThemePackageError,
    appearance_from_theme,
    available_theme_presets,
    duplicate_theme,
    export_theme,
    import_theme,
    save_current_as_theme,
    theme_metadata,
    themes_root,
    update_theme,
)

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
    reload_theme_requested = Signal()
    dataset_review_requested = Signal()
    dataset_export_requested = Signal()

    def __init__(
        self,
        key_config: KeyConfig,
        settings: AppSettings | None = None,
        prompt_registry: LocalAIPromptRegistry | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings-window")
        self.setWindowTitle("Uttate Settings")
        self.resize(780, 560)
        self.key_config = key_config
        self.app_settings = settings or AppSettings()
        self.prompt_registry = prompt_registry or LocalAIPromptRegistry.load()

        self.mode_buttons: dict[str, QPushButton] = {}
        self._building_controls = True
        self.language_combo = QComboBox()
        self.language_combo.addItem("日本語", "ja")
        self.language_combo.addItem("English", "en")
        language_index = self.language_combo.findData(self.app_settings.general.language)
        self.language_combo.setCurrentIndex(max(0, language_index))
        self.theme_preset_combo = QComboBox()
        for preset in available_theme_presets():
            self.theme_preset_combo.addItem(preset, preset)
        self.theme_preset_combo.setCurrentIndex(
            max(0, self.theme_preset_combo.findData(self.app_settings.appearance.theme_preset))
        )
        self.custom_css_path = QLineEdit(self.app_settings.appearance.custom_css_path)
        current_metadata = theme_metadata(self.app_settings.appearance.theme_preset)
        self.theme_name = QLineEdit(str(current_metadata.get("name", "")))
        self.theme_id = QLineEdit(str(current_metadata.get("theme_id", "")))
        self.theme_author = QLineEdit(str(current_metadata.get("author", "user")))
        self.theme_version = QLineEdit(str(current_metadata.get("version", "1.0.0")))
        self.theme_description = QPlainTextEdit(str(current_metadata.get("description", "")))
        self.theme_description.setMaximumHeight(56)
        self.theme_preview_image = QLineEdit(str(current_metadata.get("preview_image", "")))
        self.save_theme_button = QPushButton("Save current as new theme")
        self.update_theme_button = QPushButton("Update current theme")
        self.duplicate_theme_button = QPushButton("Duplicate theme")
        self.export_theme_button = QPushButton("Export theme")
        self.import_theme_button = QPushButton("Import theme")
        self.reload_css_button = QPushButton("Reload CSS")
        self.open_theme_folder_button = QPushButton("Open theme folder")
        self.reset_theme_button = QPushButton("Reset theme")
        self.font_family_combo = QComboBox()
        self.font_family_combo.addItem("sans-serif", "sans-serif")
        for family in sorted(set(QFontDatabase.families())):
            self.font_family_combo.addItem(family, family)
        font_index = self.font_family_combo.findData(self.app_settings.appearance.font_family)
        self.font_family_combo.setCurrentIndex(max(0, font_index))
        self.ui_font_size = self._spin_box(self.app_settings.appearance.ui_font_size, 8, 36)
        self.review_font_size = self._spin_box(self.app_settings.appearance.review_font_size, 8, 48)
        self.input_font_size = self._spin_box(self.app_settings.appearance.input_font_size, 8, 48)
        self.queue_font_size = self._spin_box(self.app_settings.appearance.queue_font_size, 8, 36)
        self.shortcut_font_size = self._spin_box(
            self.app_settings.appearance.shortcut_font_size, 8, 30
        )
        self.debug_font_size = self._spin_box(self.app_settings.appearance.debug_font_size, 8, 36)
        self.preview_text = QLineEdit(self.app_settings.appearance.preview_text)
        self.review_bg_image_path = QLineEdit(self.app_settings.appearance.review_bg_image_path)
        self.review_bg_opacity = self._ratio_box(self.app_settings.appearance.review_bg_opacity)
        self.review_bg_blur = self._spin_box(self.app_settings.appearance.review_bg_blur, 0, 80)
        self.review_overlay = self._ratio_box(self.app_settings.appearance.review_overlay)
        self.review_image_fit = self._image_fit_combo(self.app_settings.appearance.review_image_fit)
        self.review_image_position = QLineEdit(self.app_settings.appearance.review_image_position)
        self.review_panel_opacity = self._ratio_box(
            self.app_settings.appearance.review_panel_opacity
        )
        self.review_corner_radius = self._spin_box(
            self.app_settings.appearance.review_corner_radius, 0, 40
        )
        self.input_bg_image_path = QLineEdit(self.app_settings.appearance.input_bg_image_path)
        self.input_bg_opacity = self._ratio_box(self.app_settings.appearance.input_bg_opacity)
        self.input_bg_blur = self._spin_box(self.app_settings.appearance.input_bg_blur, 0, 80)
        self.input_overlay = self._ratio_box(self.app_settings.appearance.input_overlay)
        self.input_image_fit = self._image_fit_combo(self.app_settings.appearance.input_image_fit)
        self.input_image_position = QLineEdit(self.app_settings.appearance.input_image_position)
        self.input_panel_opacity = self._ratio_box(self.app_settings.appearance.input_panel_opacity)
        self.input_corner_radius = self._spin_box(
            self.app_settings.appearance.input_corner_radius, 0, 40
        )
        self.debug_bg_image_path = QLineEdit(self.app_settings.appearance.debug_bg_image_path)
        self.debug_bg_opacity = self._ratio_box(self.app_settings.appearance.debug_bg_opacity)
        self.debug_bg_blur = self._spin_box(self.app_settings.appearance.debug_bg_blur, 0, 80)
        self.debug_overlay = self._ratio_box(self.app_settings.appearance.debug_overlay)
        self.debug_panel_opacity = self._ratio_box(self.app_settings.appearance.debug_panel_opacity)
        self.dataset_collection_checkbox = QCheckBox("Dataset Collection Mode")
        self.dataset_collection_checkbox.setChecked(self.app_settings.dataset.collection_enabled)
        self.dataset_capture_checkbox = QCheckBox("Enable explicit dataset candidate capture")
        self.dataset_capture_checkbox.setChecked(self.app_settings.dataset.capture_enabled)
        self.dataset_history_checkbox = QCheckBox("Save conversion history")
        self.dataset_history_checkbox.setChecked(self.app_settings.dataset.save_conversion_history)
        self.dataset_auto_create_candidates = QCheckBox("Auto-create dataset candidates")
        self.dataset_auto_create_candidates.setChecked(
            self.app_settings.dataset.auto_create_candidates
        )
        self.dataset_warn_external_api = QCheckBox("Warn when external API is active")
        self.dataset_warn_external_api.setChecked(
            self.app_settings.dataset.warn_external_api_active
        )
        self.open_dataset_review_button = QPushButton("Open DatasetReviewWindow")
        self.export_whitelisted_dataset_button = QPushButton("Export whitelisted dataset")
        self.dataset_store_path = QLineEdit(self._dataset_store_text())
        self.dataset_store_path.setPlaceholderText(str(default_dataset_history_path()))
        self.review_pending_count = QComboBox()
        for count in (1, 3, 5):
            self.review_pending_count.addItem(str(count), count)
        pending_count_index = self.review_pending_count.findData(
            self.app_settings.review_hud.visible_pending_count
        )
        self.review_pending_count.setCurrentIndex(max(0, pending_count_index))
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
        self._building_controls = False
        self._select_mode("global")
        self._populate_prompt_profiles()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.addTab(_scroll_tab(self._build_general_tab(), "settingsGeneralScroll"), "General")
        self.tabs.addTab(
            _scroll_tab(self._build_appearance_tab(), "settingsAppearanceScroll"),
            "Appearance",
        )
        self.tabs.addTab(_scroll_tab(self._build_hud_tab(), "settingsHudScroll"), "HUD")
        self.tabs.addTab(
            _scroll_tab(self._build_dataset_tab(), "settingsDatasetScroll"),
            "Privacy / Dataset",
        )
        self.tabs.addTab(
            _scroll_tab(self._build_prompt_tab(), "settingsPromptScroll"),
            "Prompts",
        )
        self.tabs.addTab(
            _scroll_tab(self._build_shortcuts_tab(), "settingsShortcutsScroll"),
            "Shortcuts",
        )
        layout.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        group = QGroupBox("Language")
        group_layout = QVBoxLayout(group)
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel("Language"))
        language_row.addWidget(self.language_combo)
        language_row.addStretch(1)
        group_layout.addLayout(language_row)
        layout.addWidget(group)
        layout.addStretch(1)
        return tab

    def _build_appearance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._build_appearance_group())
        layout.addWidget(self._build_font_group())
        layout.addStretch(1)
        return tab

    def _build_hud_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._build_hud_group())
        layout.addStretch(1)
        return tab

    def _build_dataset_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._build_dataset_group())
        layout.addStretch(1)
        return tab

    def _build_prompt_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._build_prompt_group(), 1)
        return tab

    def _build_shortcuts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

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
        layout.addLayout(action_bar)
        return tab

    def _build_appearance_group(self) -> QGroupBox:
        group = QGroupBox("Appearance")
        layout = QVBoxLayout(group)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme preset"))
        theme_row.addWidget(self.theme_preset_combo)
        theme_row.addWidget(QLabel("Custom CSS path"))
        theme_row.addWidget(self.custom_css_path, 1)
        layout.addLayout(theme_row)
        meta_row = QHBoxLayout()
        meta_row.addWidget(QLabel("Name"))
        meta_row.addWidget(self.theme_name)
        meta_row.addWidget(QLabel("Theme ID"))
        meta_row.addWidget(self.theme_id)
        meta_row.addWidget(QLabel("Author"))
        meta_row.addWidget(self.theme_author)
        meta_row.addWidget(QLabel("Version"))
        meta_row.addWidget(self.theme_version)
        layout.addLayout(meta_row)
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Preview image"))
        preview_row.addWidget(self.theme_preview_image, 1)
        layout.addLayout(preview_row)
        description_row = QHBoxLayout()
        description_row.addWidget(QLabel("Description"))
        description_row.addWidget(self.theme_description, 1)
        layout.addLayout(description_row)
        management_row = QHBoxLayout()
        management_row.addWidget(self.save_theme_button)
        management_row.addWidget(self.update_theme_button)
        management_row.addWidget(self.duplicate_theme_button)
        management_row.addWidget(self.export_theme_button)
        management_row.addWidget(self.import_theme_button)
        management_row.addStretch(1)
        layout.addLayout(management_row)
        action_row = QHBoxLayout()
        action_row.addWidget(self.reload_css_button)
        action_row.addWidget(self.open_theme_folder_button)
        action_row.addWidget(self.reset_theme_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        return group

    def _build_font_group(self) -> QGroupBox:
        group = QGroupBox("Font")
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(QLabel("System font"))
        row.addWidget(self.font_family_combo)
        row.addWidget(QLabel("UI"))
        row.addWidget(self.ui_font_size)
        row.addWidget(QLabel("Review"))
        row.addWidget(self.review_font_size)
        row.addWidget(QLabel("Input"))
        row.addWidget(self.input_font_size)
        row.addWidget(QLabel("Queue"))
        row.addWidget(self.queue_font_size)
        row.addWidget(QLabel("Shortcut"))
        row.addWidget(self.shortcut_font_size)
        row.addWidget(QLabel("Debug"))
        row.addWidget(self.debug_font_size)
        layout.addLayout(row)
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Preview text"))
        preview_row.addWidget(self.preview_text, 1)
        layout.addLayout(preview_row)
        return group

    def _build_dataset_group(self) -> QGroupBox:
        group = QGroupBox("Privacy / Dataset")
        layout = QVBoxLayout(group)
        layout.addWidget(self.dataset_collection_checkbox)
        layout.addWidget(self.dataset_capture_checkbox)
        layout.addWidget(self.dataset_history_checkbox)
        layout.addWidget(self.dataset_auto_create_candidates)
        layout.addWidget(self.dataset_warn_external_api)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Dataset review store"))
        path_row.addWidget(self.dataset_store_path, 1)
        layout.addLayout(path_row)
        action_row = QHBoxLayout()
        action_row.addWidget(self.open_dataset_review_button)
        action_row.addWidget(self.export_whitelisted_dataset_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)
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
        layout.addWidget(self._build_panel_appearance_group("ReviewHUD", "review"))
        layout.addWidget(self._build_panel_appearance_group("InputPanel", "input"))
        layout.addWidget(self._build_debug_appearance_group())
        return group

    def _build_panel_appearance_group(self, title: str, prefix: str) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        image_path = getattr(self, f"{prefix}_bg_image_path")
        opacity = getattr(self, f"{prefix}_bg_opacity")
        blur = getattr(self, f"{prefix}_bg_blur")
        overlay = getattr(self, f"{prefix}_overlay")
        fit = getattr(self, f"{prefix}_image_fit")
        position = getattr(self, f"{prefix}_image_position")
        panel_opacity = getattr(self, f"{prefix}_panel_opacity")
        radius = getattr(self, f"{prefix}_corner_radius")
        image_row = QHBoxLayout()
        image_row.addWidget(QLabel("Background image path"))
        image_row.addWidget(image_path, 1)
        layout.addLayout(image_row)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Opacity"))
        controls.addWidget(opacity)
        controls.addWidget(QLabel("Blur"))
        controls.addWidget(blur)
        controls.addWidget(QLabel("Overlay"))
        controls.addWidget(overlay)
        controls.addWidget(QLabel("Fit"))
        controls.addWidget(fit)
        controls.addWidget(QLabel("Position"))
        controls.addWidget(position)
        controls.addWidget(QLabel("Panel opacity"))
        controls.addWidget(panel_opacity)
        controls.addWidget(QLabel("Radius"))
        controls.addWidget(radius)
        layout.addLayout(controls)
        return group

    def _build_debug_appearance_group(self) -> QGroupBox:
        group = QGroupBox("DebugConsole")
        layout = QVBoxLayout(group)
        image_row = QHBoxLayout()
        image_row.addWidget(QLabel("Background image path"))
        image_row.addWidget(self.debug_bg_image_path, 1)
        layout.addLayout(image_row)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Opacity"))
        controls.addWidget(self.debug_bg_opacity)
        controls.addWidget(QLabel("Blur"))
        controls.addWidget(self.debug_bg_blur)
        controls.addWidget(QLabel("Overlay"))
        controls.addWidget(self.debug_overlay)
        controls.addWidget(QLabel("Panel opacity"))
        controls.addWidget(self.debug_panel_opacity)
        layout.addLayout(controls)
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
        self.save_theme_button.clicked.connect(self._save_current_as_new_theme)
        self.update_theme_button.clicked.connect(self._update_current_theme)
        self.duplicate_theme_button.clicked.connect(self._duplicate_current_theme)
        self.export_theme_button.clicked.connect(self._export_current_theme)
        self.import_theme_button.clicked.connect(self._import_theme)
        self.reload_css_button.clicked.connect(self._reload_css)
        self.open_theme_folder_button.clicked.connect(self._open_theme_folder)
        self.reset_theme_button.clicked.connect(self._reset_theme)
        self.dataset_collection_checkbox.toggled.connect(self._sync_dataset_controls)
        self.open_dataset_review_button.clicked.connect(self.dataset_review_requested.emit)
        self.export_whitelisted_dataset_button.clicked.connect(self.dataset_export_requested.emit)
        self._sync_dataset_controls(self.dataset_collection_checkbox.isChecked())
        self._connect_appearance_signals()
        self.prompt_close_button.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self.prompt_apply_button.setShortcut(QKeySequence("Ctrl+R"))
        self.prompt_apply_close_button.setShortcut(QKeySequence("Ctrl+Return"))
        QShortcut(QKeySequence("Ctrl+Enter"), self).activated.connect(
            self._apply_prompt_changes_and_close
        )

    def _connect_appearance_signals(self) -> None:
        self.theme_preset_combo.currentIndexChanged.connect(self._theme_preset_changed)
        combo_boxes = [self.font_family_combo, self.review_image_fit, self.input_image_fit]
        for combo_box in combo_boxes:
            combo_box.currentIndexChanged.connect(self._emit_live_appearance)
        line_edits = [
            self.custom_css_path,
            self.preview_text,
            self.review_bg_image_path,
            self.review_image_position,
            self.input_bg_image_path,
            self.input_image_position,
            self.debug_bg_image_path,
        ]
        for line_edit in line_edits:
            line_edit.editingFinished.connect(self._emit_live_appearance)
        spin_boxes = [
            self.ui_font_size,
            self.review_font_size,
            self.input_font_size,
            self.queue_font_size,
            self.shortcut_font_size,
            self.debug_font_size,
            self.review_bg_opacity,
            self.review_bg_blur,
            self.review_overlay,
            self.review_panel_opacity,
            self.review_corner_radius,
            self.input_bg_opacity,
            self.input_bg_blur,
            self.input_overlay,
            self.input_panel_opacity,
            self.input_corner_radius,
            self.debug_bg_opacity,
            self.debug_bg_blur,
            self.debug_overlay,
            self.debug_panel_opacity,
        ]
        for spin_box in spin_boxes:
            spin_box.valueChanged.connect(self._emit_live_appearance)

    def _theme_preset_changed(self, *_args: object) -> None:
        if self._building_controls:
            return
        theme_id = self._selected_theme_id()
        self._load_theme_metadata(theme_id)
        appearance = appearance_from_theme(theme_id)
        if appearance is not None:
            self._set_appearance_controls(appearance)
        else:
            self.app_settings = replace(
                self.app_settings,
                appearance=replace(
                    self._appearance_from_controls(),
                    theme_preset=theme_id,
                    custom_css_path="",
                ),
            )
        self._emit_live_appearance()

    def _save_current_as_new_theme(self) -> None:
        try:
            theme_id = save_current_as_theme(
                replace(self.app_settings, appearance=self._appearance_from_controls()),
                name=self.theme_name.text().strip() or "Custom Theme",
                theme_id=self._new_theme_id_text(),
                author=self.theme_author.text().strip() or "user",
                version=self.theme_version.text().strip() or "1.0.0",
                description=self.theme_description.toPlainText(),
                preview_image=self.theme_preview_image.text().strip(),
            )
        except (OSError, ThemePackageError) as error:
            QMessageBox.warning(self, "Theme save failed", str(error))
            return
        self._refresh_theme_presets(theme_id)
        self._emit_live_appearance()

    def _update_current_theme(self) -> None:
        theme_id = self._selected_theme_id()
        if theme_id in BUILT_IN_THEME_IDS:
            QMessageBox.information(
                self,
                "Duplicate required",
                "Built-in themes cannot be updated directly. Use Duplicate theme first.",
            )
            return
        try:
            update_theme(
                replace(self.app_settings, appearance=self._appearance_from_controls()),
                name=self.theme_name.text().strip() or theme_id,
                theme_id=theme_id,
                author=self.theme_author.text().strip() or "user",
                version=self.theme_version.text().strip() or "1.0.0",
                description=self.theme_description.toPlainText(),
                preview_image=self.theme_preview_image.text().strip(),
            )
        except (OSError, ThemePackageError) as error:
            QMessageBox.warning(self, "Theme update failed", str(error))
            return
        self._refresh_theme_presets(theme_id)
        self._emit_live_appearance()

    def _duplicate_current_theme(self) -> None:
        try:
            theme_id = duplicate_theme(
                self._selected_theme_id(),
                name=self.theme_name.text().strip() or "",
                theme_id=self._new_theme_id_text(),
            )
        except (OSError, ThemePackageError) as error:
            QMessageBox.warning(self, "Theme duplicate failed", str(error))
            return
        self._refresh_theme_presets(theme_id)
        self._load_theme_metadata(theme_id)
        self._emit_live_appearance()

    def _export_current_theme(self) -> None:
        destination_text, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export theme",
            f"{self._selected_theme_id()}.uttate-theme.zip",
            "Uttate theme (*.uttate-theme.zip);;Zip files (*.zip)",
        )
        if not destination_text:
            return
        try:
            export_theme(self._selected_theme_id(), Path(destination_text))
        except (OSError, ThemePackageError) as error:
            QMessageBox.warning(self, "Theme export failed", str(error))

    def _import_theme(self) -> None:
        package_text, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import theme",
            "",
            "Uttate theme (*.uttate-theme.zip);;Zip files (*.zip)",
        )
        if not package_text:
            return
        try:
            theme_id = import_theme(Path(package_text))
        except (OSError, ThemePackageError, zipfile.BadZipFile) as error:
            QMessageBox.warning(self, "Theme import failed", str(error))
            return
        self._refresh_theme_presets(theme_id)
        self._load_theme_metadata(theme_id)
        self._emit_live_appearance()

    def _refresh_theme_presets(self, selected_theme_id: str) -> None:
        self._building_controls = True
        self.theme_preset_combo.clear()
        for preset in available_theme_presets():
            self.theme_preset_combo.addItem(preset, preset)
        self.theme_preset_combo.setCurrentIndex(
            max(0, self.theme_preset_combo.findData(selected_theme_id))
        )
        self._building_controls = False

    def _load_theme_metadata(self, theme_id: str) -> None:
        try:
            data = theme_metadata(theme_id)
        except (OSError, ThemePackageError, ValueError):
            data = {}
        self.theme_name.setText(str(data.get("name", theme_id)))
        self.theme_id.setText(str(data.get("theme_id", theme_id)))
        self.theme_author.setText(str(data.get("author", "user")))
        self.theme_version.setText(str(data.get("version", "1.0.0")))
        self.theme_description.setPlainText(str(data.get("description", "")))
        self.theme_preview_image.setText(str(data.get("preview_image", "")))

    def _selected_theme_id(self) -> str:
        theme_id = self.theme_preset_combo.currentData()
        return theme_id if isinstance(theme_id, str) else "default"

    def _new_theme_id_text(self) -> str:
        raw_theme_id = self.theme_id.text().strip()
        return "" if raw_theme_id == self._selected_theme_id() else raw_theme_id

    def _emit_live_appearance(self, *_args: object) -> None:
        if self._building_controls:
            return
        self.app_settings = replace(
            self.app_settings,
            appearance=self._appearance_from_controls(),
        )
        self.app_settings_saved.emit(self.app_settings)

    def _reload_css(self) -> None:
        self._emit_live_appearance()
        self.reload_theme_requested.emit()

    def _open_theme_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(themes_root())))

    def _reset_theme(self) -> None:
        self._set_appearance_controls(AppearanceSettings())
        self._emit_live_appearance()

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
                collection_enabled=self.dataset_collection_checkbox.isChecked(),
                save_conversion_history=self.dataset_history_checkbox.isChecked(),
                auto_create_candidates=self.dataset_auto_create_candidates.isChecked(),
                warn_external_api_active=self.dataset_warn_external_api.isChecked(),
                review_store_path=self.dataset_store_path.text().strip(),
            ),
            general=GeneralSettings(language=str(self.language_combo.currentData())),
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
                always_on_top=self.app_settings.input_panel.always_on_top,
            ),
            appearance=self._appearance_from_controls(),
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
        return self.app_settings.dataset.review_store_path or str(default_dataset_history_path())

    def _sync_dataset_controls(self, enabled: bool) -> None:
        for widget in (
            self.dataset_capture_checkbox,
            self.dataset_history_checkbox,
            self.dataset_auto_create_candidates,
            self.dataset_warn_external_api,
            self.dataset_store_path,
            self.open_dataset_review_button,
            self.export_whitelisted_dataset_button,
        ):
            widget.setEnabled(enabled)

    def _selected_prompt_profile_name(self) -> str | None:
        profile_name = self.prompt_profile_combo.currentData()
        return profile_name if isinstance(profile_name, str) else None

    def _appearance_from_controls(self) -> AppearanceSettings:
        return AppearanceSettings(
            theme_preset=str(self.theme_preset_combo.currentData()),
            custom_css_path=self.custom_css_path.text().strip(),
            font_family=str(self.font_family_combo.currentData()),
            ui_font_size=self.ui_font_size.value(),
            review_font_size=self.review_font_size.value(),
            input_font_size=self.input_font_size.value(),
            queue_font_size=self.queue_font_size.value(),
            shortcut_font_size=self.shortcut_font_size.value(),
            debug_font_size=self.debug_font_size.value(),
            preview_text=self.preview_text.text(),
            review_bg_image_path=self.review_bg_image_path.text().strip(),
            review_bg_opacity=self.review_bg_opacity.value(),
            review_bg_blur=self.review_bg_blur.value(),
            review_overlay=self.review_overlay.value(),
            review_image_fit=str(self.review_image_fit.currentData()),
            review_image_position=self.review_image_position.text().strip() or "center",
            review_panel_opacity=self.review_panel_opacity.value(),
            review_corner_radius=self.review_corner_radius.value(),
            input_bg_image_path=self.input_bg_image_path.text().strip(),
            input_bg_opacity=self.input_bg_opacity.value(),
            input_bg_blur=self.input_bg_blur.value(),
            input_overlay=self.input_overlay.value(),
            input_image_fit=str(self.input_image_fit.currentData()),
            input_image_position=self.input_image_position.text().strip() or "center",
            input_panel_opacity=self.input_panel_opacity.value(),
            input_corner_radius=self.input_corner_radius.value(),
            debug_bg_image_path=self.debug_bg_image_path.text().strip(),
            debug_bg_opacity=self.debug_bg_opacity.value(),
            debug_bg_blur=self.debug_bg_blur.value(),
            debug_overlay=self.debug_overlay.value(),
            debug_panel_opacity=self.debug_panel_opacity.value(),
        )

    def _set_appearance_controls(self, appearance: AppearanceSettings) -> None:
        self._building_controls = True
        self.theme_preset_combo.setCurrentIndex(
            max(0, self.theme_preset_combo.findData(appearance.theme_preset))
        )
        self.custom_css_path.setText(appearance.custom_css_path)
        self.font_family_combo.setCurrentIndex(
            max(0, self.font_family_combo.findData(appearance.font_family))
        )
        self.ui_font_size.setValue(appearance.ui_font_size)
        self.review_font_size.setValue(appearance.review_font_size)
        self.input_font_size.setValue(appearance.input_font_size)
        self.queue_font_size.setValue(appearance.queue_font_size)
        self.shortcut_font_size.setValue(appearance.shortcut_font_size)
        self.debug_font_size.setValue(appearance.debug_font_size)
        self.preview_text.setText(appearance.preview_text)
        self.review_bg_image_path.setText(appearance.review_bg_image_path)
        self.review_bg_opacity.setValue(appearance.review_bg_opacity)
        self.review_bg_blur.setValue(appearance.review_bg_blur)
        self.review_overlay.setValue(appearance.review_overlay)
        self.review_image_fit.setCurrentIndex(
            max(0, self.review_image_fit.findData(appearance.review_image_fit))
        )
        self.review_image_position.setText(appearance.review_image_position)
        self.review_panel_opacity.setValue(appearance.review_panel_opacity)
        self.review_corner_radius.setValue(appearance.review_corner_radius)
        self.input_bg_image_path.setText(appearance.input_bg_image_path)
        self.input_bg_opacity.setValue(appearance.input_bg_opacity)
        self.input_bg_blur.setValue(appearance.input_bg_blur)
        self.input_overlay.setValue(appearance.input_overlay)
        self.input_image_fit.setCurrentIndex(
            max(0, self.input_image_fit.findData(appearance.input_image_fit))
        )
        self.input_image_position.setText(appearance.input_image_position)
        self.input_panel_opacity.setValue(appearance.input_panel_opacity)
        self.input_corner_radius.setValue(appearance.input_corner_radius)
        self.debug_bg_image_path.setText(appearance.debug_bg_image_path)
        self.debug_bg_opacity.setValue(appearance.debug_bg_opacity)
        self.debug_bg_blur.setValue(appearance.debug_bg_blur)
        self.debug_overlay.setValue(appearance.debug_overlay)
        self.debug_panel_opacity.setValue(appearance.debug_panel_opacity)
        self._building_controls = False

    @staticmethod
    def _spin_box(value: int, minimum: int, maximum: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setValue(value)
        return box

    @staticmethod
    def _ratio_box(value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0.0, 1.0)
        box.setSingleStep(0.05)
        box.setDecimals(2)
        box.setValue(value)
        return box

    @staticmethod
    def _image_fit_combo(value: str) -> QComboBox:
        combo = QComboBox()
        for option in ("cover", "contain", "tile", "stretch"):
            combo.addItem(option, option)
        combo.setCurrentIndex(max(0, combo.findData(value)))
        return combo


def _scroll_tab(widget: QWidget, object_name: str) -> QScrollArea:
    scroll_area = QScrollArea()
    scroll_area.setObjectName(object_name)
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll_area.setWidget(widget)
    return scroll_area
