from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar
from uuid import uuid4

JsonObject = dict[str, Any]


class ChunkStatus(StrEnum):
    """Lifecycle states for one rough-input chunk."""

    RAW = "raw"
    QUEUED = "queued"
    CONVERTING = "converting"
    READY_FOR_REVIEW = "ready_for_review"
    ADOPTED = "adopted"
    EDITED = "edited"
    REJECTED = "rejected"
    FAILED = "failed"


class ExportFallback(StrEnum):
    """How unresolved chunks are rendered during export."""

    CANDIDATE_1 = "candidate_1"
    RAW = "raw"


class InvalidStatusTransition(ValueError):
    """Raised when a chunk is moved through an unsupported lifecycle edge."""


@dataclass(slots=True)
class Chunk:
    """A committed unit of rough input and all conversion results derived from it."""

    raw_text: str
    id: str = field(default_factory=lambda: str(uuid4()))
    candidate_1: str | None = None
    candidate_2: str | None = None
    adopted_text: str | None = None
    uncertain: list[JsonObject] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    status: ChunkStatus = ChunkStatus.RAW
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    _ALLOWED_TRANSITIONS: ClassVar[dict[ChunkStatus, frozenset[ChunkStatus]]] = {
        ChunkStatus.RAW: frozenset({ChunkStatus.QUEUED}),
        ChunkStatus.QUEUED: frozenset({ChunkStatus.CONVERTING, ChunkStatus.FAILED}),
        ChunkStatus.CONVERTING: frozenset({ChunkStatus.READY_FOR_REVIEW, ChunkStatus.FAILED}),
        ChunkStatus.READY_FOR_REVIEW: frozenset(
            {
                ChunkStatus.ADOPTED,
                ChunkStatus.EDITED,
                ChunkStatus.REJECTED,
                ChunkStatus.QUEUED,
            }
        ),
        ChunkStatus.ADOPTED: frozenset({ChunkStatus.EDITED, ChunkStatus.QUEUED}),
        ChunkStatus.EDITED: frozenset(
            {ChunkStatus.ADOPTED, ChunkStatus.REJECTED, ChunkStatus.QUEUED}
        ),
        ChunkStatus.REJECTED: frozenset({ChunkStatus.QUEUED}),
        ChunkStatus.FAILED: frozenset({ChunkStatus.REJECTED, ChunkStatus.QUEUED}),
    }

    def __post_init__(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("raw_text must contain non-whitespace characters.")
        if not self.id:
            raise ValueError("id must not be empty.")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")

    def transition_to(self, next_status: ChunkStatus, *, at: float | None = None) -> None:
        """Move the chunk to an allowed state and update its modification time."""

        allowed = self._ALLOWED_TRANSITIONS[self.status]
        if next_status not in allowed:
            raise InvalidStatusTransition(
                f"Cannot transition chunk {self.id} from {self.status} to {next_status}."
            )

        updated_at = self._validated_update_time(at)
        self.status = next_status
        self.updated_at = updated_at
        if next_status != ChunkStatus.FAILED:
            self.error_message = None

    def mark_failed(self, message: str, *, at: float | None = None) -> None:
        """Record a processing failure while preserving all existing chunk text."""

        if not message.strip():
            raise ValueError("A failure message must not be empty.")
        self.transition_to(ChunkStatus.FAILED, at=at)
        self.error_message = message

    def adopt(self, text: str, *, at: float | None = None) -> None:
        """Adopt the currently previewed candidate from review mode."""

        self._require_text(text)
        if self.status not in {ChunkStatus.READY_FOR_REVIEW, ChunkStatus.EDITED}:
            raise InvalidStatusTransition(
                f"Cannot adopt text while chunk {self.id} is {self.status}."
            )
        self.transition_to(ChunkStatus.ADOPTED, at=at)
        self.adopted_text = text

    def edit(self, text: str, *, at: float | None = None) -> None:
        """Store an explicit user edit without losing the generated candidates."""

        self._require_text(text)
        if self.status not in {
            ChunkStatus.READY_FOR_REVIEW,
            ChunkStatus.ADOPTED,
            ChunkStatus.EDITED,
        }:
            raise InvalidStatusTransition(
                f"Cannot edit text while chunk {self.id} is {self.status}."
            )

        if self.status != ChunkStatus.EDITED:
            self.transition_to(ChunkStatus.EDITED, at=at)
        else:
            self.updated_at = self._validated_update_time(at)
        self.adopted_text = text

    def reject(self, *, at: float | None = None) -> None:
        """Keep the chunk in history while marking it unusable for approval."""

        if self.status not in {
            ChunkStatus.READY_FOR_REVIEW,
            ChunkStatus.EDITED,
            ChunkStatus.FAILED,
        }:
            raise InvalidStatusTransition(
                f"Cannot reject chunk {self.id} while it is {self.status}."
            )
        self.transition_to(ChunkStatus.REJECTED, at=at)

    def export_text(self, fallback: ExportFallback = ExportFallback.CANDIDATE_1) -> str:
        """Return the chunk text using the configured unresolved fallback."""

        if self.adopted_text is not None:
            return self.adopted_text
        if fallback == ExportFallback.CANDIDATE_1 and self.candidate_1 is not None:
            return self.candidate_1
        return self.raw_text

    def _validated_update_time(self, at: float | None) -> float:
        updated_at = time.time() if at is None else at
        if updated_at < self.updated_at:
            raise ValueError("A chunk update cannot move updated_at backwards.")
        return updated_at

    @staticmethod
    def _require_text(text: str) -> None:
        if not text.strip():
            raise ValueError("Adopted or edited text must not be empty.")


@dataclass(slots=True)
class Document:
    """An ordered collection of chunks representing one Uttate document."""

    title: str = "Untitled"
    id: str = field(default_factory=lambda: str(uuid4()))
    chunks: list[Chunk] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title must contain non-whitespace characters.")
        if not self.id:
            raise ValueError("id must not be empty.")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")
        self._ensure_unique_chunk_ids()

    def add_chunk(self, raw_text: str, *, at: float | None = None) -> Chunk:
        """Create and append a raw chunk."""

        timestamp = time.time() if at is None else at
        if timestamp < self.updated_at:
            raise ValueError("A document update cannot move updated_at backwards.")
        chunk = Chunk(raw_text=raw_text, created_at=timestamp, updated_at=timestamp)
        self.chunks.append(chunk)
        self.updated_at = timestamp
        return chunk

    def append_chunk(self, chunk: Chunk, *, at: float | None = None) -> None:
        """Append an existing chunk while protecting document ordering and identity."""

        if any(existing.id == chunk.id for existing in self.chunks):
            raise ValueError(f"Chunk id {chunk.id} already exists in document {self.id}.")
        timestamp = time.time() if at is None else at
        if timestamp < self.updated_at:
            raise ValueError("A document update cannot move updated_at backwards.")
        self.chunks.append(chunk)
        self.updated_at = timestamp

    def chunk_by_id(self, chunk_id: str) -> Chunk:
        """Return a chunk by identity."""

        for chunk in self.chunks:
            if chunk.id == chunk_id:
                return chunk
        raise KeyError(chunk_id)

    def export_text(
        self,
        fallback: ExportFallback = ExportFallback.CANDIDATE_1,
        *,
        separator: str = "\n",
    ) -> str:
        """Render chunks in document order using the selected fallback policy."""

        return separator.join(chunk.export_text(fallback) for chunk in self.chunks)

    def _ensure_unique_chunk_ids(self) -> None:
        chunk_ids = [chunk.id for chunk in self.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("A document cannot contain duplicate chunk ids.")
