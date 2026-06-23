from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from uttate.models import Chunk, ChunkStatus
from uttate.providers.base import ConversionProvider, ConversionResult


class _WorkerSignals(QObject):
    completed = Signal(str, object)
    failed = Signal(str, str)


class _ConversionWorker(QRunnable):
    def __init__(self, chunk_id: str, raw_text: str, provider: ConversionProvider) -> None:
        super().__init__()
        self.chunk_id = chunk_id
        self.raw_text = raw_text
        self.provider = provider
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.provider.convert(self.raw_text)
        except Exception as error:  # noqa: BLE001 - worker errors must return to the UI
            self.signals.failed.emit(self.chunk_id, str(error) or type(error).__name__)
            return
        self.signals.completed.emit(self.chunk_id, result)


class ConversionQueue(QObject):
    """Run synchronous providers in a thread pool and update chunks on the UI thread."""

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

    @property
    def active_count(self) -> int:
        return self._active_count

    def enqueue(self, chunk: Chunk) -> None:
        if chunk.id in self._workers:
            raise ValueError(f"Chunk {chunk.id} is already being converted.")

        chunk.transition_to(ChunkStatus.NORMALIZING)
        self._chunks[chunk.id] = chunk
        worker = _ConversionWorker(chunk.id, chunk.raw_text, self._provider)
        worker.signals.completed.connect(self._handle_completed)
        worker.signals.failed.connect(self._handle_failed)
        self._workers[chunk.id] = worker

        self._active_count += 1
        self.chunk_updated.emit(chunk.id)
        self.processing_count_changed.emit(self._active_count)
        self._thread_pool.start(worker)

    def wait_for_done(self, timeout_ms: int = -1) -> bool:
        return self._thread_pool.waitForDone(timeout_ms)

    @Slot(str, object)
    def _handle_completed(self, chunk_id: str, raw_result: object) -> None:
        chunk = self._chunks[chunk_id]
        try:
            if not isinstance(raw_result, ConversionResult):
                raise TypeError("The conversion provider returned an invalid result.")
            self._apply_result(chunk, raw_result)
        except Exception as error:  # noqa: BLE001 - convert pipeline errors to chunk failures
            self._mark_failed(chunk, str(error) or type(error).__name__)
        finally:
            self.chunk_updated.emit(chunk_id)
            self._finish_worker(chunk_id)

    @Slot(str, str)
    def _handle_failed(self, chunk_id: str, message: str) -> None:
        chunk = self._chunks[chunk_id]
        self._mark_failed(chunk, message)
        self.chunk_updated.emit(chunk_id)
        self._finish_worker(chunk_id)

    @staticmethod
    def _apply_result(chunk: Chunk, result: ConversionResult) -> None:
        chunk.normalized = result.normalized
        chunk.segments = list(result.segments)
        chunk.uncertain = list(result.uncertain)
        chunk.transition_to(ChunkStatus.NORMALIZED)

        if result.candidate_1 is None and result.candidate_2 is None:
            return
        if result.candidate_1 is None or result.candidate_2 is None:
            raise ValueError("Both review candidates must be present when conversion continues.")

        chunk.transition_to(ChunkStatus.RETRIEVING_DICTIONARY)
        chunk.dictionary_candidates = list(result.dictionary_candidates)

        chunk.transition_to(ChunkStatus.CONVERTING)
        chunk.candidate_1 = result.candidate_1
        chunk.candidate_2 = result.candidate_2
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
