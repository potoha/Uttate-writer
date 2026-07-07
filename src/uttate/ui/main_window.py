from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QThreadPool, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from uttate.addons.dataset_curator import add_candidate
from uttate.config import AppSettings, ProviderSettings, default_dataset_capture_path, save_settings
from uttate.keymap import GLOBAL_MODE, KeyConfig
from uttate.models import Chunk, ChunkStatus, Document, InvalidStatusTransition
from uttate.pipeline.queue import ConversionQueue
from uttate.prompts.registry import LocalAIPromptRegistry
from uttate.providers.base import ConversionProvider, ProviderError
from uttate.providers.factory import create_conversion_provider
from uttate.ui.chunk_list import ChunkListWidget
from uttate.ui.debug_console import DebugConsole
from uttate.ui.input_panel import InputPanel
from uttate.ui.provider_panel import ProviderPanel
from uttate.ui.review_hud import ReviewHUD, is_hud_chunk
from uttate.ui.review_panel import ReviewPanel
from uttate.ui.settings_window import SettingsWindow


class ConsoleMode(StrEnum):
    INPUT = "Input"
    REVIEW = "Review"
    CANDIDATE_EDIT = "Candidate edit"


class MainWindow(QMainWindow):
    """M2 window joining rough input, asynchronous conversion, and review."""

    def __init__(
        self,
        provider: ConversionProvider | None = None,
        *,
        settings: AppSettings | None = None,
        prompt_registry: LocalAIPromptRegistry | None = None,
        max_workers: int = 2,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Uttate Writer")
        self.setMinimumSize(640, 220)
        self._configure_main_window_geometry()

        self.document = Document()
        self.settings = settings or AppSettings()
        self.prompt_registry = prompt_registry
        self.key_config = KeyConfig.load()
        self._settings_window: SettingsWindow | None = None
        self._global_shortcuts: list[QShortcut] = []
        initial_provider = provider or _provider_from_settings(
            self.settings.provider,
            prompt_registry=(
                self._prompt_registry() if self.settings.provider.type == "local_ai" else None
            ),
        )
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(max_workers)
        self.conversion_queue = ConversionQueue(initial_provider, self.thread_pool, parent=self)
        self.mode = ConsoleMode.INPUT
        self._saved_input_text: str | None = None
        self._editing_chunk_id: str | None = None
        self._editing_candidate_index = 0

        self.chunk_list = ChunkListWidget()
        self.provider_panel = ProviderPanel(self.settings.provider)
        self.input_panel = InputPanel(
            self.key_config,
            self.settings.provider,
            self.settings.input_panel,
        )
        self.review_panel = ReviewPanel()
        self.review_hud = ReviewHUD(self.settings.review_hud)
        self.debug_console = DebugConsole(self.provider_panel, self.chunk_list, self.review_panel)
        self.review_hud.setWindowFlag(Qt.WindowType.Window, True)
        self.input_panel.setWindowFlag(Qt.WindowType.Window, True)
        self.debug_console.setWindowFlag(Qt.WindowType.Window, True)
        self.review_hud.setWindowTitle("Uttate ReviewHUD")
        self.debug_console.setWindowTitle("Uttate DebugConsole")
        self._build_layout()
        self._connect_signals()
        self._refresh_global_shortcuts()
        self._apply_style()
        self.statusBar().showMessage("Ready")
        self._update_provider_ui()
        self._refresh_review_hud()
        self.show_input_panel()

    def show(self) -> None:  # type: ignore[override]
        """Keep the QMainWindow as a hidden root and show managed windows instead."""

        self.hide()
        self.show_input_panel()
        self.ensure_review_hud_visible()

    @Slot(str)
    def commit_chunk(self, raw_text: str) -> None:
        if not raw_text.strip():
            return
        chunk = self.document.add_chunk(raw_text)
        self.chunk_list.add_chunk(chunk)
        self.chunk_list.setCurrentRow(self.chunk_list.count() - 1)
        self.chunk_list.scrollToBottom()
        self.conversion_queue.enqueue(chunk)
        self._refresh_review_hud(selected_chunk_id=chunk.id)
        self.input_panel.editor.setFocus()

    @Slot(str)
    def _send_input_panel_text(self, raw_text: str) -> None:
        self._send_input_panel(raw_text)

    @Slot()
    def _send_input_panel(self, raw_text: str | None = None) -> None:
        text = self.input_panel.editor.toPlainText() if raw_text is None else raw_text
        if not text.strip():
            return
        self.input_panel.set_send_enabled(False)
        try:
            if self.mode == ConsoleMode.CANDIDATE_EDIT:
                self._reconvert_candidate_edit()
            else:
                self.input_panel.editor.clear()
                self.commit_chunk(text)
        finally:
            self.input_panel.set_send_enabled(True)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API name
        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)

        key_event = event
        if not isinstance(key_event, QKeyEvent):
            return super().eventFilter(watched, event)

        global_action = self.key_config.action_for(GLOBAL_MODE, key_event)
        if global_action == "open_settings":
            self._open_settings_window()
            key_event.accept()
            return True
        if global_action == "toggle_input_review":
            self._toggle_mode()
            key_event.accept()
            return True
        if global_action == "toggle_debug_console":
            self._toggle_debug_console()
            key_event.accept()
            return True

        if self.mode == ConsoleMode.CANDIDATE_EDIT and self._handle_candidate_edit_key(key_event):
            key_event.accept()
            return True
        if self.mode == ConsoleMode.REVIEW and self._handle_review_key(key_event):
            key_event.accept()
            return True

        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        self.conversion_queue.wait_for_done(2000)
        for window in (
            self.review_hud,
            self.input_panel,
            self.debug_console,
            self._settings_window,
        ):
            if window is not None:
                window.close()
        super().closeEvent(event)

    def _build_layout(self) -> None:
        console = QWidget()
        layout = QVBoxLayout(console)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(console)

    def _connect_signals(self) -> None:
        self.input_panel.editor.commit_requested.connect(self.commit_chunk)
        self.input_panel.editor.send_requested.connect(self._send_input_panel_text)
        self.input_panel.send_requested.connect(self._send_input_panel)
        self.input_panel.editor.escape_on_empty_requested.connect(self.input_panel.close)
        self.input_panel.editor.mode_toggle_requested.connect(self._toggle_mode)
        self.input_panel.provider_change_requested.connect(self._change_provider)
        self.input_panel.settings_requested.connect(self._open_settings_window)
        self.provider_panel.provider_change_requested.connect(self._change_provider)
        self.provider_panel.settings_requested.connect(self._open_settings_window)
        self.review_hud.always_show_changed.connect(self._set_review_hud_always_show)
        self.chunk_list.currentItemChanged.connect(self._show_selected_chunk)
        self.conversion_queue.chunk_updated.connect(self._refresh_chunk)
        self.conversion_queue.processing_count_changed.connect(self._show_processing_count)
        self.input_panel.editor.installEventFilter(self)
        self.chunk_list.installEventFilter(self)
        self.review_hud.installEventFilter(self)
        self.review_hud.queue.installEventFilter(self)
        self.input_panel.installEventFilter(self)

    @Slot(str)
    def _change_provider(self, provider_type: str) -> None:
        next_settings = replace(self.settings.provider, type=provider_type)
        try:
            provider = _provider_from_settings(
                next_settings,
                prompt_registry=(
                    self._prompt_registry() if next_settings.type == "local_ai" else None
                ),
            )
        except Exception as error:  # noqa: BLE001 - provider setup errors are user-visible
            self.provider_panel.set_settings(self.settings.provider, error=str(error))
            self.statusBar().showMessage(f"Provider switch failed: {error}")
            return

        self.settings = replace(self.settings, provider=next_settings)
        self.conversion_queue.set_provider(provider)
        self.provider_panel.set_settings(next_settings)
        self._update_provider_ui()
        self.statusBar().showMessage(f"Provider: {provider_type} / {_model_text(next_settings)}")

    @Slot()
    def _show_selected_chunk(self) -> None:
        chunk_id = self.chunk_list.selected_chunk_id()
        if chunk_id is None:
            self.review_panel.show_chunk(None)
            return
        self.review_panel.show_chunk(self.document.chunk_by_id(chunk_id))

    @Slot(str)
    def _refresh_chunk(self, chunk_id: str) -> None:
        chunk = self.document.chunk_by_id(chunk_id)
        self.chunk_list.update_chunk(chunk)
        if self.chunk_list.selected_chunk_id() == chunk_id:
            self.review_panel.show_chunk(chunk)
        self._refresh_review_hud(selected_chunk_id=chunk_id)
        if self.mode == ConsoleMode.REVIEW and self._selected_chunk() is None:
            self._select_actionable_chunk(prefer_latest=True)

    @Slot(int)
    def _show_processing_count(self, active_count: int) -> None:
        if active_count:
            self.statusBar().showMessage(f"Converting {active_count} chunk(s) - keep typing")
        else:
            self.statusBar().showMessage(f"Ready - {len(self.document.chunks)} chunk(s)")

    def _configure_main_window_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1100, 280)
            return

        available = screen.availableGeometry()
        height = max(220, int(available.height() * 0.25))
        self.setGeometry(available.x(), available.bottom() - height + 1, available.width(), height)

    @Slot()
    def _toggle_mode(self) -> None:
        if self.mode == ConsoleMode.CANDIDATE_EDIT:
            self._cancel_candidate_edit()
            return
        if self.settings.review_hud.always_show:
            self.mode = ConsoleMode.REVIEW
            self.input_panel.set_mode_label(ConsoleMode.REVIEW.value)
            self.show_review_hud()
            self.statusBar().showMessage("ReviewHUD shown")
            return
        self._set_mode(ConsoleMode.REVIEW if self.mode == ConsoleMode.INPUT else ConsoleMode.INPUT)

    @Slot()
    def _toggle_debug_console(self) -> None:
        if self.debug_console.isVisible():
            self.debug_console.close()
            self.statusBar().showMessage("Debug console hidden")
            return
        self.show_debug_console()
        self.statusBar().showMessage("Debug console shown")

    def show_review_hud(self) -> None:
        self._refresh_review_hud()
        self._show_and_focus(self.review_hud)

    def ensure_review_hud_visible(self) -> None:
        if self.settings.review_hud.always_show:
            self._show_and_focus(self.review_hud)

    def show_input_panel(
        self,
        *,
        mode: ConsoleMode | None = None,
        initial_text: str | None = None,
    ) -> None:
        if mode is not None:
            self.mode = mode
            self.input_panel.set_mode_label(mode.value)
        if initial_text is not None:
            self.input_panel.editor.setPlainText(initial_text)
            self.input_panel.editor.moveCursor(QTextCursor.MoveOperation.End)
        self._update_provider_ui()
        self._show_and_focus(self.input_panel)
        self.input_panel.editor.setFocus()

    def show_debug_console(self) -> None:
        self._show_and_focus(self.debug_console)

    @staticmethod
    def _show_and_focus(window: QWidget) -> None:
        window.show()
        window.raise_()
        window.activateWindow()

    def _set_mode(self, mode: ConsoleMode) -> None:
        self.mode = mode
        self.input_panel.set_mode_label(mode.value)
        if mode == ConsoleMode.REVIEW:
            if not self._selected_chunk() or not self._is_actionable(self._selected_chunk()):
                self._select_actionable_chunk(prefer_latest=True)
            self.show_review_hud()
            self.review_hud.queue.setFocus()
            self.statusBar().showMessage("Review mode")
        elif mode == ConsoleMode.CANDIDATE_EDIT:
            self.show_input_panel(mode=mode)
            self.statusBar().showMessage(
                "Candidate edit - Enter accepts, Ctrl+Enter reconverts, Esc cancels"
            )
        else:
            self.show_input_panel(mode=mode)
            self.statusBar().showMessage("Input mode")

    def _handle_review_key(self, event: QKeyEvent) -> bool:
        action = self.key_config.action_for("review", event)
        if action == "return_to_input":
            if not self.settings.review_hud.always_show:
                self.review_hud.hide()
            self.show_input_panel(mode=ConsoleMode.INPUT)
            return True
        if action == "move_previous_chunk":
            self._move_review_selection(-1)
            return True
        if action == "move_next_chunk":
            self._move_review_selection(1)
            return True
        if action == "cycle_candidate":
            self._cycle_candidate_or_move_next()
            return True
        if action == "accept_candidate":
            self._accept_selected_chunk()
            return True
        if action == "accept_candidate_for_dataset":
            self._accept_selected_chunk(record_dataset=True)
            return True
        if action == "reject_chunk":
            self._reject_selected_chunk()
            return True
        if action == "edit_as_input":
            self._edit_selected_chunk()
            return True
        if action == "edit_candidate":
            self._begin_candidate_edit()
            return True
        if action == "reconvert_chunk":
            self._resend_selected_chunk()
            return True
        return False

    def _handle_candidate_edit_key(self, event: QKeyEvent) -> bool:
        action = self.key_config.action_for("candidate_edit", event)
        if action == "cancel_edit":
            self._cancel_candidate_edit()
            return True
        if action == "reconvert_edited_text":
            self._reconvert_candidate_edit()
            return True
        if action == "accept_edit":
            self._accept_candidate_edit()
            return True
        if action == "insert_space":
            self.input_panel.editor.insertPlainText(" ")
            return True
        return False

    @Slot()
    def _open_settings_window(self) -> None:
        if self._settings_window is not None and self._settings_window.isVisible():
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        self._settings_window = SettingsWindow(
            self.key_config,
            self.settings,
            self._prompt_registry(),
            None,
        )
        self._settings_window.key_config_saved.connect(self._apply_key_config)
        self._settings_window.app_settings_saved.connect(self._apply_app_settings)
        self._settings_window.local_ai_prompts_saved.connect(self._apply_local_ai_prompts)
        self._settings_window.show()

    @Slot(object)
    def _apply_key_config(self, key_config: KeyConfig) -> None:
        self.key_config = key_config
        self.input_panel.editor.set_key_config(key_config)
        self._refresh_global_shortcuts()
        self.statusBar().showMessage("Key settings saved")

    @Slot(object)
    def _apply_app_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.review_hud.set_settings(settings.review_hud)
        self.input_panel.set_settings(settings.input_panel)
        self._refresh_review_hud()
        self._update_provider_ui()
        self.ensure_review_hud_visible()
        self.statusBar().showMessage("Settings saved")

    @Slot(bool)
    def _set_review_hud_always_show(self, enabled: bool) -> None:
        if self.settings.review_hud.always_show == enabled:
            return
        self.settings = replace(
            self.settings,
            review_hud=replace(self.settings.review_hud, always_show=enabled),
        )
        self.review_hud.set_settings(self.settings.review_hud)
        if self._settings_window is not None:
            self._settings_window.app_settings = self.settings
            self._settings_window.always_show_review_hud.setChecked(enabled)
        try:
            save_settings(self.settings)
        except OSError as error:
            self.statusBar().showMessage(f"ReviewHUD setting save failed: {error}")
        if enabled:
            self.show_review_hud()

    @Slot(object)
    def _apply_local_ai_prompts(self, prompt_registry: LocalAIPromptRegistry) -> None:
        self.prompt_registry = prompt_registry
        if self.settings.provider.type != "local_ai":
            self.statusBar().showMessage("Local AI prompts saved")
            return
        try:
            provider = _provider_from_settings(
                self.settings.provider,
                prompt_registry=self.prompt_registry,
            )
        except Exception as error:  # noqa: BLE001 - provider setup errors are user-visible
            self.provider_panel.set_settings(self.settings.provider, error=str(error))
            self.statusBar().showMessage(f"Prompt apply failed: {error}")
            return
        self.conversion_queue.set_provider(provider)
        self.provider_panel.set_settings(self.settings.provider)
        self._update_provider_ui()
        self.statusBar().showMessage("Local AI prompts saved and applied")

    def _prompt_registry(self) -> LocalAIPromptRegistry:
        if self.prompt_registry is None:
            self.prompt_registry = LocalAIPromptRegistry.load()
        return self.prompt_registry

    def _refresh_global_shortcuts(self) -> None:
        for shortcut in self._global_shortcuts:
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._global_shortcuts = []

        for key in self.key_config.keys_for(GLOBAL_MODE, "open_settings"):
            sequence = QKeySequence(key)
            if sequence.isEmpty():
                continue
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(self._open_settings_window)
            self._global_shortcuts.append(shortcut)
        for key in self.key_config.keys_for(GLOBAL_MODE, "toggle_debug_console"):
            sequence = QKeySequence(key)
            if sequence.isEmpty():
                continue
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(self._toggle_debug_console)
            self._global_shortcuts.append(shortcut)

    def _selected_chunk(self) -> Chunk | None:
        chunk_id = self.review_hud.selected_chunk_id() or self.chunk_list.selected_chunk_id()
        if chunk_id is None:
            return None
        return self.document.chunk_by_id(chunk_id)

    def _select_chunk(self, chunk_id: str) -> None:
        for row in range(self.chunk_list.count()):
            item = self.chunk_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == chunk_id:
                self.chunk_list.setCurrentRow(row)
                self.chunk_list.scrollToItem(item)
                break
        self.review_panel.show_chunk(self.document.chunk_by_id(chunk_id))
        self._refresh_review_hud(selected_chunk_id=chunk_id)

    def _refresh_review_hud(self, *, selected_chunk_id: str | None = None) -> None:
        chunk_ids = [
            chunk.id
            for chunk in self.document.chunks
            if is_hud_chunk(
                chunk,
                auto_remove_accepted=self.settings.review_hud.auto_remove_accepted,
                editing_chunk_id=self._editing_chunk_id,
            )
        ]
        if selected_chunk_id is not None and selected_chunk_id not in chunk_ids:
            selected_chunk_id = chunk_ids[0] if chunk_ids else None
        self.review_hud.set_chunks(
            chunk_ids,
            self.document.chunk_by_id,
            selected_chunk_id=selected_chunk_id,
            editing_chunk_id=self._editing_chunk_id,
        )
        self.ensure_review_hud_visible()

    def _update_provider_ui(self) -> None:
        self.provider_panel.set_settings(self.settings.provider)
        self.input_panel.set_provider_settings(self.settings.provider)

    @staticmethod
    def _is_actionable(chunk: Chunk | None) -> bool:
        return chunk is not None and chunk.status in {
            ChunkStatus.READY_FOR_REVIEW,
            ChunkStatus.EDITED,
            ChunkStatus.FAILED,
        }

    def _actionable_rows(self) -> list[int]:
        rows: list[int] = []
        for index, chunk in enumerate(self.document.chunks):
            if self._is_actionable(chunk):
                rows.append(index)
        return rows

    def _select_actionable_chunk(self, *, prefer_latest: bool) -> None:
        rows = self._actionable_rows()
        if not rows:
            self.statusBar().showMessage("Review mode - no pending or error chunks")
            return
        chunk = self.document.chunks[rows[-1] if prefer_latest else rows[0]]
        self._select_chunk(chunk.id)

    def _move_review_selection(self, direction: int) -> None:
        rows = self._actionable_rows()
        if not rows:
            self.statusBar().showMessage("Review mode - no pending or error chunks")
            return
        selected = self._selected_chunk()
        current_row = (
            self.document.chunks.index(selected)
            if selected in self.document.chunks
            else -1
        )
        if current_row not in rows:
            self._select_chunk(self.document.chunks[rows[-1]].id)
            return

        next_index = (rows.index(current_row) + direction) % len(rows)
        self._select_chunk(self.document.chunks[rows[next_index]].id)

    def _cycle_candidate_or_move_next(self) -> None:
        chunk = self._selected_chunk()
        if not self._is_actionable(chunk):
            self._move_review_selection(1)
            return
        if chunk and chunk.candidate_1 and chunk.candidate_2:
            next_index = 0 if self.review_hud.candidate_index(chunk.id) == 1 else 1
            self.review_hud.set_candidate_index(chunk.id, next_index)
            self.chunk_list.set_candidate_index(chunk.id, next_index)
            self.chunk_list.update_chunk(chunk)
            self.review_panel.show_chunk(chunk)
            self.statusBar().showMessage(f"Candidate {'B' if next_index else 'A'} selected")
            return
        self._move_review_selection(1)

    def _accept_selected_chunk(self, *, record_dataset: bool = False) -> None:
        chunk = self._selected_chunk()
        if chunk is None or chunk.status not in {ChunkStatus.READY_FOR_REVIEW, ChunkStatus.EDITED}:
            self.statusBar().showMessage("Select a pending chunk to accept")
            return
        if record_dataset and not self.settings.dataset.capture_enabled:
            self.statusBar().showMessage("Dataset capture is disabled")
            return

        text = self._selected_candidate_text(chunk)
        try:
            chunk.adopt(text)
        except InvalidStatusTransition as error:
            self.statusBar().showMessage(str(error))
            return

        QApplication.clipboard().setText(text)
        self.chunk_list.update_chunk(chunk)
        self.review_panel.show_chunk(chunk)
        self._refresh_review_hud()
        message = "Accepted and copied to clipboard"
        if record_dataset:
            try:
                candidate = self._add_dataset_candidate(chunk, text)
            except (OSError, ValueError) as error:
                message = f"Accepted and copied; dataset capture failed: {error}"
            else:
                message = f"Accepted, copied, and recorded {candidate['id']}"
        self.statusBar().showMessage(message)
        self._select_actionable_chunk(prefer_latest=True)

    def _reject_selected_chunk(self) -> None:
        chunk = self._selected_chunk()
        if not self._is_actionable(chunk):
            self.statusBar().showMessage("Select a pending or error chunk to reject")
            return
        try:
            chunk.reject()
        except InvalidStatusTransition as error:
            self.statusBar().showMessage(str(error))
            return

        self.chunk_list.update_chunk(chunk)
        self.review_panel.show_chunk(chunk)
        self._refresh_review_hud()
        self.statusBar().showMessage("Rejected")
        self._select_actionable_chunk(prefer_latest=True)

    def _edit_selected_chunk(self) -> None:
        chunk = self._selected_chunk()
        if chunk is None:
            return
        self.show_input_panel(
            mode=ConsoleMode.INPUT,
            initial_text=self._selected_candidate_text(chunk),
        )

    def _begin_candidate_edit(self) -> None:
        chunk = self._selected_chunk()
        if chunk is None or chunk.status not in {ChunkStatus.READY_FOR_REVIEW, ChunkStatus.EDITED}:
            self.statusBar().showMessage("Select a pending chunk to edit its candidate")
            return

        candidate_text = self._selected_candidate_text(chunk)
        if not candidate_text.strip():
            self.statusBar().showMessage("Selected chunk has no editable candidate")
            return

        self._saved_input_text = self.input_panel.editor.toPlainText()
        self._editing_chunk_id = chunk.id
        self._editing_candidate_index = self.review_hud.candidate_index(chunk.id)
        self._refresh_review_hud(selected_chunk_id=chunk.id)
        self.show_input_panel(mode=ConsoleMode.CANDIDATE_EDIT, initial_text=candidate_text)

    def _accept_candidate_edit(self) -> None:
        chunk = self._editing_chunk()
        if chunk is None:
            self._restore_input_after_candidate_edit()
            self._set_mode(ConsoleMode.REVIEW)
            return

        text = self.input_panel.editor.toPlainText()
        if not text.strip():
            self.statusBar().showMessage("Edited candidate must not be empty")
            return

        self._set_candidate_text(chunk, text)
        try:
            chunk.adopt(text)
        except InvalidStatusTransition as error:
            self.statusBar().showMessage(str(error))
            return

        QApplication.clipboard().setText(text)
        self.chunk_list.update_chunk(chunk)
        self.review_panel.show_chunk(chunk)
        self._restore_input_after_candidate_edit()
        self._refresh_review_hud()
        self._set_mode(ConsoleMode.REVIEW)
        self.statusBar().showMessage("Edited candidate accepted and copied to clipboard")

    def _reconvert_candidate_edit(self) -> None:
        chunk = self._editing_chunk()
        if chunk is None:
            self._restore_input_after_candidate_edit()
            self._set_mode(ConsoleMode.REVIEW)
            return

        text = self.input_panel.editor.toPlainText()
        if not text.strip():
            self.statusBar().showMessage("Reconversion text must not be empty")
            return

        chunk.raw_text = text
        chunk.candidate_1 = None
        chunk.candidate_2 = None
        chunk.adopted_text = None
        chunk.uncertain = []
        chunk.error_message = None
        try:
            self.conversion_queue.enqueue(chunk)
        except Exception as error:  # noqa: BLE001 - user-visible retry failure
            self.statusBar().showMessage(f"Reconvert failed: {error}")
            return

        self.chunk_list.update_chunk(chunk)
        self.review_panel.show_chunk(chunk)
        self._restore_input_after_candidate_edit()
        self._refresh_review_hud(selected_chunk_id=chunk.id)
        self._set_mode(ConsoleMode.REVIEW)
        self.statusBar().showMessage("Edited candidate sent for reconversion")

    def _cancel_candidate_edit(self) -> None:
        self._restore_input_after_candidate_edit()
        self._refresh_review_hud()
        self._set_mode(ConsoleMode.REVIEW)
        self.statusBar().showMessage("Candidate edit canceled")

    def _resend_selected_chunk(self) -> None:
        chunk = self._selected_chunk()
        if chunk is None:
            return
        if chunk.status in {ChunkStatus.QUEUED, ChunkStatus.CONVERTING}:
            self.statusBar().showMessage("Chunk is already processing")
            return
        try:
            self.conversion_queue.enqueue(chunk)
        except Exception as error:  # noqa: BLE001 - user-visible retry failure
            self.statusBar().showMessage(f"Resend failed: {error}")
            return
        self.chunk_list.update_chunk(chunk)
        self._refresh_review_hud(selected_chunk_id=chunk.id)
        self.statusBar().showMessage("Resent chunk")

    def _selected_candidate_text(self, chunk: Chunk) -> str:
        if self.review_hud.candidate_index(chunk.id) == 1 and chunk.candidate_2:
            return chunk.candidate_2
        return chunk.candidate_1 or chunk.adopted_text or chunk.raw_text

    def _add_dataset_candidate(self, chunk: Chunk, selected_text: str) -> dict[str, object]:
        selected_index = self.review_hud.candidate_index(chunk.id)
        literal = selected_text if selected_index == 0 else chunk.candidate_1 or selected_text
        natural = selected_text if selected_index == 1 else chunk.candidate_2 or selected_text
        tags = ["review-accept"]
        if chunk.provider:
            tags.append(f"provider:{chunk.provider}")
        if chunk.model:
            tags.append(f"model:{chunk.model}")

        return add_candidate(
            self._dataset_capture_store_path(),
            raw=chunk.raw_text,
            kana=chunk.raw_text,
            literal=literal,
            natural=natural,
            source="review_accept",
            tags=tags,
        )

    def _dataset_capture_store_path(self) -> Path:
        configured = self.settings.dataset.capture_store_path.strip()
        return Path(configured) if configured else default_dataset_capture_path()

    def _editing_chunk(self) -> Chunk | None:
        if self._editing_chunk_id is None:
            return None
        try:
            return self.document.chunk_by_id(self._editing_chunk_id)
        except KeyError:
            return None

    def _set_candidate_text(self, chunk: Chunk, text: str) -> None:
        if self._editing_candidate_index == 1:
            chunk.candidate_2 = text
        else:
            chunk.candidate_1 = text

    def _restore_input_after_candidate_edit(self) -> None:
        self.input_panel.editor.setPlainText(self._saved_input_text or "")
        self.input_panel.editor.moveCursor(QTextCursor.MoveOperation.End)
        self._saved_input_text = None
        self._editing_chunk_id = None
        self._editing_candidate_index = 0

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QLabel#sectionTitle {
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#sectionHint {
                color: #6b7280;
            }
            QPlainTextEdit, QListWidget {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px;
            }
            QLabel#providerModelLabel {
                color: #374151;
            }
            QLabel#providerErrorLabel {
                color: #b91c1c;
            }
            """
        )


def _provider_from_settings(
    settings: ProviderSettings,
    *,
    prompt_registry: LocalAIPromptRegistry | None = None,
) -> ConversionProvider:
    try:
        return create_conversion_provider(settings, prompt_registry=prompt_registry)
    except ProviderError:
        raise


def _model_text(settings: ProviderSettings) -> str:
    if settings.type == "gemini":
        return settings.gemini_model
    if settings.type == "openai":
        return settings.openai_model
    if settings.type == "local_ai":
        return settings.compatible_model or "auto-detect"
    return "local_ai"
