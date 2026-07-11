from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from uttate.models import Chunk, ChunkStatus
from uttate.providers.base import ConversionProvider, ProviderResult

LOGGER = logging.getLogger(__name__)


class _WorkerSignals(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str)


class _ConversionWorker(QRunnable):
    def __init__(
        self,
        chunk_id: str,
        raw_text: str,
        provider: ConversionProvider,
        *,
        previous_context: str,
        candidate_count: int,
    ) -> None:
        super().__init__()
        self.chunk_id = chunk_id
        self.raw_text = raw_text
        self.provider = provider
        self.previous_context = previous_context
        self.candidate_count = candidate_count
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.provider.convert(
                self.raw_text,
                previous_context=self.previous_context,
                candidate_count=self.candidate_count,
            )
        except Exception as error:  # noqa: BLE001 - worker errors must return to the UI
            LOGGER.exception(
                "Conversion worker failed chunk_id=%s provider=%s raw_length=%s",
                self.chunk_id,
                type(self.provider).__name__,
                len(self.raw_text),
            )
            self.signals.failed.emit(self.chunk_id, str(error) or type(error).__name__)
            return
        self.signals.completed.emit(self.chunk_id, result)


class ConversionQueue(QObject):
    """Run synchronous providers in a thread pool and update chunks on the UI thread.

    Project B treats conversion as a single provider call. Local multi-stage pipelines can
    return later as another provider, but the queue should not know about their internals.
    """

    chunk_updated = Signal(str)
    processing_count_changed = Signal(int)

    def __init__(
        self,
        provider: ConversionProvider,
        thread_pool: QThreadPool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._thread_pool = thread_pool
        self._chunks: dict[str, Chunk] = {}
        self._workers: dict[str, _ConversionWorker] = {}
        self._active_count = 0
        self._accepting_work = True

    @property
    def active_count(self) -> int:
        return self._active_count

    def set_provider(self, provider: ConversionProvider) -> None:
        """Use a new provider for future chunks without disturbing active workers."""

        self._provider = provider

    def stop_accepting_work(self) -> None:
        """Prevent new work while allowing active workers to finish safely."""

        self._accepting_work = False

    def enqueue(
        self,
        chunk: Chunk,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> None:
        if not self._accepting_work:
            raise RuntimeError("The conversion queue is shutting down.")
        if chunk.id in self._workers:
            raise ValueError(f"Chunk {chunk.id} is already being converted.")
        if candidate_count <= 0:
            raise ValueError("candidate_count must be positive.")

        chunk.transition_to(ChunkStatus.QUEUED)
        self._chunks[chunk.id] = chunk
        worker = _ConversionWorker(
            chunk.id,
            chunk.raw_text,
            self._provider,
            previous_context=previous_context,
            candidate_count=candidate_count,
        )
        worker.signals.completed.connect(self._handle_completed)
        worker.signals.failed.connect(self._handle_failed)
        self._workers[chunk.id] = worker

        self._active_count += 1
        self.chunk_updated.emit(chunk.id)
        self.processing_count_changed.emit(self._active_count)
        chunk.transition_to(ChunkStatus.CONVERTING)
        self.chunk_updated.emit(chunk.id)
        self._thread_pool.start(worker)

    def wait_for_done(self, timeout_ms: int = -1) -> bool:
        return self._thread_pool.waitForDone(timeout_ms)

    @Slot(str, object)
    def _handle_completed(self, chunk_id: str, raw_result: object) -> None:
        chunk = self._chunks[chunk_id]
        try:
            if not isinstance(raw_result, ProviderResult):
                raise TypeError("The conversion provider returned an invalid result.")
            self._apply_result(chunk, raw_result)
        except Exception as error:  # noqa: BLE001 - convert pipeline errors to chunk failures
            LOGGER.exception("Failed to apply provider result chunk_id=%s", chunk_id)
            self._mark_failed(chunk, str(error) or type(error).__name__)
        finally:
            self.chunk_updated.emit(chunk_id)
            self._finish_worker(chunk_id)

    @Slot(str, str)
    def _handle_failed(self, chunk_id: str, message: str) -> None:
        chunk = self._chunks[chunk_id]
        LOGGER.warning("Marking chunk failed chunk_id=%s message=%s", chunk_id, message)
        self._mark_failed(chunk, message)
        self.chunk_updated.emit(chunk_id)
        self._finish_worker(chunk_id)

    @staticmethod
    def _apply_result(chunk: Chunk, result: ProviderResult) -> None:
        # The UI still displays two slots because candidate comparison is the MVP gesture.
        # Providers may return one candidate, but candidate_2 stays empty rather than faked.
        chunk.candidate_1 = result.candidates[0].text
        chunk.candidate_2 = result.candidates[1].text if len(result.candidates) > 1 else None
        chunk.uncertain = list(result.uncertain)
        chunk.provider = result.provider or None
        chunk.model = result.model or None
        chunk.transition_to(ChunkStatus.READY_FOR_REVIEW)

    @staticmethod
    def _mark_failed(chunk: Chunk, message: str) -> None:
        try:
            chunk.mark_failed(message)
        except Exception as error:  # noqa: BLE001 - preserve the original and internal failure
            chunk.error_message = f"{message} (failed to record state: {error})"

    def _finish_worker(self, chunk_id: str) -> None:
        self._workers.pop(chunk_id, None)
        self._active_count -= 1
        self.processing_count_changed.emit(self._active_count)
