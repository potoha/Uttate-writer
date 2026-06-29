from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QThreadPool, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QVBoxLayout, QWidget

from uttate.config import AppSettings, ProviderSettings
from uttate.models import Document
from uttate.pipeline.queue import ConversionQueue
from uttate.providers.base import ConversionProvider, ProviderError
from uttate.providers.factory import create_conversion_provider
from uttate.providers.mock import MockProvider
from uttate.ui.chunk_list import ChunkListWidget
from uttate.ui.input_panel import InputPanel
from uttate.ui.provider_panel import ProviderPanel
from uttate.ui.review_panel import ReviewPanel


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
        self.resize(1100, 760)
        self.setMinimumSize(820, 560)

        self.document = Document()
        self.settings = settings or AppSettings()
        initial_provider = provider or _provider_from_settings(self.settings.provider)
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(max_workers)
        self.conversion_queue = ConversionQueue(initial_provider, self.thread_pool, parent=self)

        self.chunk_list = ChunkListWidget()
        self.provider_panel = ProviderPanel(self.settings.provider)
        self.input_panel = InputPanel()
        self.review_panel = ReviewPanel()
        self._build_layout()
        self._connect_signals()
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
        self.conversion_queue.enqueue(chunk)
        self.input_panel.editor.setFocus()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        self.conversion_queue.wait_for_done(2000)
        super().closeEvent(event)

    def _build_layout(self) -> None:
        left_title = QLabel("Draft / Chunks")
        left_title.setObjectName("sectionTitle")
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 6, 12)
        left_layout.addWidget(left_title)
        left_layout.addWidget(self.chunk_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.addWidget(self.provider_panel)
        right_layout.addWidget(self.input_panel, 2)
        right_layout.addWidget(self.review_panel, 5)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([300, 800])
        self.setCentralWidget(splitter)

    def _connect_signals(self) -> None:
        self.input_panel.editor.commit_requested.connect(self.commit_chunk)
        self.provider_panel.provider_change_requested.connect(self._change_provider)
        self.chunk_list.currentItemChanged.connect(self._show_selected_chunk)
        self.conversion_queue.chunk_updated.connect(self._refresh_chunk)
        self.conversion_queue.processing_count_changed.connect(self._show_processing_count)

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

    @Slot(int)
    def _show_processing_count(self, active_count: int) -> None:
        if active_count:
            self.statusBar().showMessage(f"Converting {active_count} chunk(s) — keep typing")
        else:
            self.statusBar().showMessage(f"Ready — {len(self.document.chunks)} chunk(s)")

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
