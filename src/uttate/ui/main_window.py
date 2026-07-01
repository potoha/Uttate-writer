from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

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

from uttate.config import AppSettings, ProviderSettings
from uttate.keymap import GLOBAL_MODE, KeyConfig
from uttate.models import Chunk, ChunkStatus, Document, InvalidStatusTransition
from uttate.pipeline.queue import ConversionQueue
from uttate.providers.base import ConversionProvider, ProviderError
from uttate.providers.factory import create_conversion_provider
from uttate.providers.mock import MockProvider
from uttate.ui.chunk_list import ChunkListWidget
from uttate.ui.input_panel import InputPanel
from uttate.ui.provider_panel import ProviderPanel
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
        max_workers: int = 2,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Uttate Writer")
        self.setMinimumSize(640, 220)
        self._configure_main_window_geometry()

        self.document = Document()
        self.settings = settings or AppSettings()
        self.key_config = KeyConfig.load()
        self._settings_window: SettingsWindow | None = None
        self._global_shortcuts: list[QShortcut] = []
        initial_provider = provider or _provider_from_settings(self.settings.provider)
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(max_workers)
        self.conversion_queue = ConversionQueue(initial_provider, self.thread_pool, parent=self)
        self.mode = ConsoleMode.INPUT
        self._saved_input_text: str | None = None
        self._editing_chunk_id: str | None = None
        self._editing_candidate_index = 0

        self.chunk_list = ChunkListWidget()
        self.provider_panel = ProviderPanel(self.settings.provider)
        self.input_panel = InputPanel(self.key_config)
        self.review_panel = ReviewPanel()
        self._build_layout()
        self._connect_signals()
        self._refresh_global_shortcuts()
        self._apply_style()
        self.statusBar().showMessage("Ready")
        self.input_panel.editor.setFocus()

    @Slot(str)
    def commit_chunk(self, raw_text: str) -> None:
        if not raw_text.strip():
            return
        chunk = self.document.add_chunk(raw_text)
        self.chunk_list.add_chunk(chunk)
        self.chunk_list.setCurrentRow(self.chunk_list.count() - 1)
        self.chunk_list.scrollToBottom()
        self.conversion_queue.enqueue(chunk)
        self.input_panel.editor.setFocus()

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

        if self.mode == ConsoleMode.CANDIDATE_EDIT and self._handle_candidate_edit_key(key_event):
            key_event.accept()
            return True
        if self.mode == ConsoleMode.REVIEW and self._handle_review_key(key_event):
            key_event.accept()
            return True

        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        self.conversion_queue.wait_for_done(2000)
        super().closeEvent(event)

    def _build_layout(self) -> None:
        console = QWidget()
        layout = QVBoxLayout(console)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        layout.addWidget(self.provider_panel)
        layout.addWidget(self.chunk_list, 1)
        layout.addWidget(self.input_panel)
        self.review_panel.setParent(self)
        self.review_panel.hide()
        self.setCentralWidget(console)

    def _connect_signals(self) -> None:
        self.input_panel.editor.commit_requested.connect(self.commit_chunk)
        self.input_panel.editor.escape_on_empty_requested.connect(self.hide)
        self.input_panel.editor.mode_toggle_requested.connect(self._toggle_mode)
        self.provider_panel.provider_change_requested.connect(self._change_provider)
        self.provider_panel.settings_requested.connect(self._open_settings_window)
        self.chunk_list.currentItemChanged.connect(self._show_selected_chunk)
        self.conversion_queue.chunk_updated.connect(self._refresh_chunk)
        self.conversion_queue.processing_count_changed.connect(self._show_processing_count)
        self.input_panel.editor.installEventFilter(self)
        self.chunk_list.installEventFilter(self)

    @Slot(str)
    def _change_provider(self, provider_type: str) -> None:
        next_settings = replace(self.settings.provider, type=provider_type)
        try:
            provider = _provider_from_settings(next_settings)
        except Exception as error:  # noqa: BLE001 - provider setup errors are user-visible
            self.provider_panel.set_settings(self.settings.provider, error=str(error))
            self.statusBar().showMessage(f"Provider switch failed: {error}")
            return

        self.settings = replace(self.settings, provider=next_settings)
        self.conversion_queue.set_provider(provider)
        self.provider_panel.set_settings(next_settings)
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
        self._set_mode(ConsoleMode.REVIEW if self.mode == ConsoleMode.INPUT else ConsoleMode.INPUT)

    def _set_mode(self, mode: ConsoleMode) -> None:
        self.mode = mode
        self.input_panel.set_mode_label(mode.value)
        if mode == ConsoleMode.REVIEW:
            if not self._selected_chunk() or not self._is_actionable(self._selected_chunk()):
                self._select_actionable_chunk(prefer_latest=True)
            self.chunk_list.setFocus()
            self.statusBar().showMessage("Review mode")
        elif mode == ConsoleMode.CANDIDATE_EDIT:
            self.input_panel.editor.setFocus()
            self.statusBar().showMessage(
                "Candidate edit - Enter accepts, Ctrl+Enter reconverts, Esc cancels"
            )
        else:
            self.input_panel.editor.setFocus()
            self.statusBar().showMessage("Input mode")

    def _handle_review_key(self, event: QKeyEvent) -> bool:
        action = self.key_config.action_for("review", event)
        if action == "return_to_input":
            self._set_mode(ConsoleMode.INPUT)
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
        self._settings_window = SettingsWindow(self.key_config, self)
        self._settings_window.key_config_saved.connect(self._apply_key_config)
        self._settings_window.show()

    @Slot(object)
    def _apply_key_config(self, key_config: KeyConfig) -> None:
        self.key_config = key_config
        self.input_panel.editor.set_key_config(key_config)
        self._refresh_global_shortcuts()
        self.statusBar().showMessage("Key settings saved")

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

    def _selected_chunk(self) -> Chunk | None:
        chunk_id = self.chunk_list.selected_chunk_id()
        if chunk_id is None:
            return None
        return self.document.chunk_by_id(chunk_id)

    @staticmethod
    def _is_actionable(chunk: Chunk | None) -> bool:
        return chunk is not None and chunk.status in {
            ChunkStatus.READY_FOR_REVIEW,
            ChunkStatus.EDITED,
            ChunkStatus.FAILED,
        }

    def _actionable_rows(self) -> list[int]:
        rows: list[int] = []
        for row in range(self.chunk_list.count()):
            item = self.chunk_list.item(row)
            chunk_id = item.data(Qt.ItemDataRole.UserRole)
            chunk = self.document.chunk_by_id(chunk_id)
            if self._is_actionable(chunk):
                rows.append(row)
        return rows

    def _select_actionable_chunk(self, *, prefer_latest: bool) -> None:
        rows = self._actionable_rows()
        if not rows:
            self.statusBar().showMessage("Review mode - no pending or error chunks")
            return
        self.chunk_list.setCurrentRow(rows[-1] if prefer_latest else rows[0])
        self.chunk_list.scrollToItem(self.chunk_list.currentItem())

    def _move_review_selection(self, direction: int) -> None:
        rows = self._actionable_rows()
        if not rows:
            self.statusBar().showMessage("Review mode - no pending or error chunks")
            return
        current_row = self.chunk_list.currentRow()
        if current_row not in rows:
            self.chunk_list.setCurrentRow(rows[-1])
            return

        next_index = (rows.index(current_row) + direction) % len(rows)
        self.chunk_list.setCurrentRow(rows[next_index])
        self.chunk_list.scrollToItem(self.chunk_list.currentItem())

    def _cycle_candidate_or_move_next(self) -> None:
        chunk = self._selected_chunk()
        if not self._is_actionable(chunk):
            self._move_review_selection(1)
            return
        if chunk and chunk.candidate_1 and chunk.candidate_2:
            next_index = 0 if self.chunk_list.candidate_index(chunk.id) == 1 else 1
            self.chunk_list.set_candidate_index(chunk.id, next_index)
            self.chunk_list.update_chunk(chunk)
            self.review_panel.show_chunk(chunk)
            self.statusBar().showMessage(f"Candidate {'B' if next_index else 'A'} selected")
            return
        self._move_review_selection(1)

    def _accept_selected_chunk(self) -> None:
        chunk = self._selected_chunk()
        if chunk is None or chunk.status not in {ChunkStatus.READY_FOR_REVIEW, ChunkStatus.EDITED}:
            self.statusBar().showMessage("Select a pending chunk to accept")
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
        self.statusBar().showMessage("Accepted and copied to clipboard")
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
        self.statusBar().showMessage("Rejected")
        self._select_actionable_chunk(prefer_latest=True)

    def _edit_selected_chunk(self) -> None:
        chunk = self._selected_chunk()
        if chunk is None:
            return
        self.input_panel.editor.setPlainText(self._selected_candidate_text(chunk))
        self.input_panel.editor.moveCursor(QTextCursor.MoveOperation.End)
        self._set_mode(ConsoleMode.INPUT)

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
        self._editing_candidate_index = self.chunk_list.candidate_index(chunk.id)
        self.input_panel.editor.setPlainText(candidate_text)
        self.input_panel.editor.moveCursor(QTextCursor.MoveOperation.End)
        self._set_mode(ConsoleMode.CANDIDATE_EDIT)

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
        self._set_mode(ConsoleMode.REVIEW)
        self.statusBar().showMessage("Edited candidate sent for reconversion")

    def _cancel_candidate_edit(self) -> None:
        self._restore_input_after_candidate_edit()
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
        self.statusBar().showMessage("Resent chunk")

    def _selected_candidate_text(self, chunk: Chunk) -> str:
        if self.chunk_list.candidate_index(chunk.id) == 1 and chunk.candidate_2:
            return chunk.candidate_2
        return chunk.candidate_1 or chunk.adopted_text or chunk.raw_text

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


def _provider_from_settings(settings: ProviderSettings) -> ConversionProvider:
    try:
        return create_conversion_provider(settings)
    except ProviderError:
        raise
    except Exception:
        if settings.type == "mock":
            return MockProvider()
        raise


def _model_text(settings: ProviderSettings) -> str:
    if settings.type == "gemini":
        return settings.gemini_model
    if settings.type == "openai":
        return settings.openai_model
    if settings.type in {"lmstudio", "openai_compatible"}:
        return settings.compatible_model or "auto-detect"
    return "mock"
