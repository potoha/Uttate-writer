import pytest

from uttate.models import (
    Chunk,
    ChunkStatus,
    Document,
    ExportFallback,
    InvalidStatusTransition,
)


def advance_to_review(chunk: Chunk) -> None:
    for status in (ChunkStatus.QUEUED, ChunkStatus.CONVERTING, ChunkStatus.READY_FOR_REVIEW):
        chunk.transition_to(status)


def test_chunk_defaults_to_raw_with_independent_collections() -> None:
    first = Chunk("first")
    second = Chunk("second")

    first.uncertain.append({"raw": "first", "reason": "example"})

    assert first.status == ChunkStatus.RAW
    assert first.id != second.id
    assert second.uncertain == []


@pytest.mark.parametrize("raw_text", ["", " ", "\r\n\t"])
def test_chunk_rejects_blank_raw_text(raw_text: str) -> None:
    with pytest.raises(ValueError, match="raw_text"):
        Chunk(raw_text)


def test_chunk_can_follow_the_complete_conversion_path() -> None:
    chunk = Chunk("rough", created_at=1.0, updated_at=1.0)
    path = (ChunkStatus.QUEUED, ChunkStatus.CONVERTING, ChunkStatus.READY_FOR_REVIEW)

    for timestamp, status in enumerate(path, start=2):
        chunk.transition_to(status, at=float(timestamp))

    assert chunk.status == ChunkStatus.READY_FOR_REVIEW
    assert chunk.updated_at == 4.0


def test_chunk_rejects_skipping_pipeline_states() -> None:
    chunk = Chunk("rough")

    with pytest.raises(InvalidStatusTransition, match="raw.*ready_for_review"):
        chunk.transition_to(ChunkStatus.READY_FOR_REVIEW)


def test_processing_failure_can_retry_without_losing_text() -> None:
    chunk = Chunk("rough")
    chunk.transition_to(ChunkStatus.QUEUED)
    chunk.mark_failed("provider unavailable")

    assert chunk.status == ChunkStatus.FAILED
    assert chunk.error_message == "provider unavailable"
    assert chunk.raw_text == "rough"

    chunk.transition_to(ChunkStatus.QUEUED)

    assert chunk.status == ChunkStatus.QUEUED
    assert chunk.error_message is None


def test_raw_chunk_cannot_be_marked_as_processing_failure() -> None:
    with pytest.raises(InvalidStatusTransition):
        Chunk("rough").mark_failed("not started")


def test_ready_chunk_can_adopt_a_candidate() -> None:
    chunk = Chunk("rough")
    advance_to_review(chunk)

    chunk.adopt("変換結果")

    assert chunk.status == ChunkStatus.ADOPTED
    assert chunk.adopted_text == "変換結果"


def test_adoption_requires_review_or_an_explicit_edit() -> None:
    with pytest.raises(InvalidStatusTransition):
        Chunk("rough").adopt("変換結果")


def test_user_edit_preserves_generated_candidates() -> None:
    chunk = Chunk("rough", candidate_1="候補A", candidate_2="候補B")
    advance_to_review(chunk)

    chunk.edit("手動編集")
    chunk.edit("再編集")

    assert chunk.status == ChunkStatus.EDITED
    assert chunk.adopted_text == "再編集"
    assert chunk.candidate_1 == "候補A"
    assert chunk.candidate_2 == "候補B"


def test_reconversion_preserves_last_adopted_text() -> None:
    chunk = Chunk("rough")
    advance_to_review(chunk)
    chunk.adopt("採用済み")

    chunk.transition_to(ChunkStatus.QUEUED)

    assert chunk.status == ChunkStatus.QUEUED
    assert chunk.adopted_text == "採用済み"
    assert chunk.export_text() == "採用済み"


def test_chunk_export_fallback_order() -> None:
    chunk = Chunk("rough", candidate_1="候補A")

    assert chunk.export_text(ExportFallback.CANDIDATE_1) == "候補A"
    assert chunk.export_text(ExportFallback.RAW) == "rough"

    chunk.adopted_text = "採用済み"
    assert chunk.export_text(ExportFallback.RAW) == "採用済み"


def test_candidate_fallback_uses_raw_when_candidate_is_missing() -> None:
    assert Chunk("rough").export_text(ExportFallback.CANDIDATE_1) == "rough"


def test_document_adds_and_finds_chunks_in_order() -> None:
    document = Document(title="Draft", created_at=1.0, updated_at=1.0)
    first = document.add_chunk("first", at=2.0)
    second = document.add_chunk("second", at=3.0)

    assert document.chunks == [first, second]
    assert document.chunk_by_id(second.id) is second
    assert document.updated_at == 3.0


def test_document_rejects_duplicate_chunk_ids() -> None:
    chunk = Chunk("rough")
    document = Document(chunks=[chunk])

    with pytest.raises(ValueError, match="already exists"):
        document.append_chunk(chunk)


def test_document_exports_chunks_in_order() -> None:
    first = Chunk("raw one", candidate_1="候補一", adopted_text="採用一")
    second = Chunk("raw two", candidate_1="候補二")
    third = Chunk("raw three")
    document = Document(title="Draft", chunks=[first, second, third])

    assert document.export_text() == "採用一\n候補二\nraw three"
    assert document.export_text(ExportFallback.RAW, separator=" | ") == (
        "採用一 | raw two | raw three"
    )


def test_document_raises_for_unknown_chunk_id() -> None:
    with pytest.raises(KeyError, match="missing"):
        Document().chunk_by_id("missing")


def test_timestamps_cannot_move_backwards() -> None:
    chunk = Chunk("rough", created_at=10.0, updated_at=10.0)

    with pytest.raises(ValueError, match="backwards"):
        chunk.transition_to(ChunkStatus.QUEUED, at=9.0)

    assert chunk.status == ChunkStatus.RAW
    assert chunk.updated_at == 10.0
