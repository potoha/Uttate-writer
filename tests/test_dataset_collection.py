from __future__ import annotations

import json

import pytest

from uttate.addons.dataset_collection import (
    HISTORY_SCHEMA,
    HISTORY_SCHEMA_VERSION,
    REVIEW_SCHEMA,
    REVIEW_SCHEMA_VERSION,
    DatasetItem,
    append_conversion_history,
    apply_dataset_redaction,
    dataset_export_summary,
    export_whitelisted_dataset,
    load_dataset_items,
    save_dataset_items,
    set_dataset_field_safety,
)
from uttate.models import Chunk, ChunkStatus


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_export_whitelisted_dataset_blocks_non_anonymized_by_default(tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    output = tmp_path / "dataset.jsonl"
    save_dataset_items(
        store,
        [
            _item("one", "whitelisted", raw_input="Alice visits Tokyo"),
            _item("two", "candidate", raw_input="candidate should stay out"),
        ],
    )

    with pytest.raises(ValueError, match="every exported field"):
        export_whitelisted_dataset(store, output)

    assert not output.exists()
    summary = dataset_export_summary(store)
    assert summary["whitelisted_count"] == 1
    assert summary["non_anonymized_count"] == 1


def test_export_whitelisted_dataset_writes_safe_finetuning_jsonl(tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    output = tmp_path / "uttate_dataset_20260708_120000.jsonl"
    save_dataset_items(
        store,
        [
            _item(
                "one",
                "whitelisted",
                raw_input="[PERSON_1] visits Tokyo",
                normalized_input="[PERSON_1] visits Tokyo",
                converted_text="Converted should not be used",
                accepted_text="Accepted should not be used",
                edited_text="Edited [PERSON_1]",
                provider="gemini",
                model="gemini-2.5-flash-lite",
                redactions=[
                    {
                        "type": "PERSON",
                        "placeholder": "[PERSON_1]",
                        "original_text": "Alice",
                        "target_field": "raw_input",
                        "start": 0,
                        "end": 5,
                        "created_at": "2026-07-08T12:00:00+09:00",
                        "replacements": [{"field": "raw_input", "original_text": "Alice"}],
                    }
                ],
            ),
            _item("two", "rejected", raw_input="rejected should stay out"),
        ],
    )

    count = export_whitelisted_dataset(store, output)

    assert count == 1
    rows = read_jsonl(output)
    assert rows == [
        {
            "raw_input": "[PERSON_1] visits Tokyo",
            "normalized_input": "[PERSON_1] visits Tokyo",
            "target_output": "Edited [PERSON_1]",
            "redactions": [
                {
                    "type": "PERSON",
                    "placeholder": "[PERSON_1]",
                    "target_field": "raw_input",
                    "start": 0,
                    "end": 5,
                    "created_at": "2026-07-08T12:00:00+09:00",
                }
            ],
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
            "created_at": "2026-07-08T12:00:00+09:00",
            "source": "uttate_writer_manual_whitelist",
            "schema_version": 1,
        }
    ]
    exported_text = output.read_text(encoding="utf-8")
    assert "Alice" not in exported_text
    assert "api_key" not in exported_text
    assert "secret" not in exported_text
    assert "converted_text" not in exported_text
    assert "accepted_text" not in exported_text
    assert "full_prompt" not in exported_text
    assert "raw_api_response" not in exported_text


def test_review_store_writes_schema_marker_and_rejects_candidate_rows(tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    save_dataset_items(store, [_item("one", "candidate", raw_input="safe")])

    row = read_jsonl(store)[0]
    assert row["schema"] == REVIEW_SCHEMA
    assert row["schema_version"] == REVIEW_SCHEMA_VERSION

    store.write_text(
        json.dumps(
            {
                "id": "cand_20260708_000001",
                "status": "candidate",
                "raw": "raw",
                "kana": "かな",
                "literal": "字義",
                "natural": "自然",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="curator candidate"):
        load_dataset_items(store)


def test_export_rejects_a_field_with_only_partial_redaction(tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    output = tmp_path / "dataset.jsonl"
    item = _item(
        "one",
        "whitelisted",
        raw_input="[PERSON_1] is safe",
        normalized_input="[PERSON_1] is safe",
        converted_text="Alice and Alice",
    )
    item["field_safety"] = {
        "raw_input": "confirmed",
        "normalized_input": "confirmed",
        "converted_text": "unreviewed",
        "edited_text": "unreviewed",
        "accepted_text": "unreviewed",
    }
    item["accepted_text"] = ""
    save_dataset_items(store, [item])
    loaded = load_dataset_items(store)[0]

    apply_dataset_redaction(
        store,
        loaded["id"],
        target_field="converted_text",
        start=0,
        end=5,
        redaction_type="PERSON",
    )

    with pytest.raises(ValueError, match="converted_text"):
        export_whitelisted_dataset(store, output)
    assert not output.exists()


def test_export_requires_each_actual_output_field_to_be_safe(tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    output = tmp_path / "dataset.jsonl"
    save_dataset_items(
        store,
        [
            _item(
                "one",
                "whitelisted",
                raw_input="reviewed input",
                normalized_input="reviewed normalized input",
                converted_text="reviewed output",
            )
        ],
    )
    item_id = load_dataset_items(store)[0]["id"]
    for field in ("raw_input", "normalized_input", "accepted_text"):
        set_dataset_field_safety(store, item_id, field=field, safety="confirmed")

    assert export_whitelisted_dataset(store, output) == 1


def test_redaction_and_undo_preserve_whitelist_status(tmp_path) -> None:
    from uttate.addons.dataset_collection import undo_last_dataset_redaction

    store = tmp_path / "dataset_review.jsonl"
    save_dataset_items(store, [_item("one", "whitelisted", raw_input="Alice")])
    item_id = load_dataset_items(store)[0]["id"]
    apply_dataset_redaction(
        store,
        item_id,
        target_field="raw_input",
        start=0,
        end=5,
        redaction_type="PERSON",
    )
    assert load_dataset_items(store)[0]["dataset_status"] == "whitelisted"

    undo_last_dataset_redaction(store, item_id)
    assert load_dataset_items(store)[0]["dataset_status"] == "whitelisted"


def test_conversion_history_is_saved_in_a_separate_schema(tmp_path) -> None:
    store = tmp_path / "conversion_history.jsonl"
    chunk = Chunk(raw_text="rough input")
    chunk.transition_to(ChunkStatus.QUEUED)
    chunk.transition_to(ChunkStatus.CONVERTING)
    chunk.candidate_1 = "候補"
    chunk.transition_to(ChunkStatus.READY_FOR_REVIEW)

    append_conversion_history(store, chunk)

    rows = read_jsonl(store)
    assert rows[0]["schema"] == HISTORY_SCHEMA
    assert rows[0]["schema_version"] == HISTORY_SCHEMA_VERSION
    assert rows[0]["raw_input"] == "rough input"
    assert rows[0]["candidate_1"] == "候補"


def test_dataset_provider_metadata_comes_from_the_converted_chunk(tmp_path) -> None:
    store = tmp_path / "dataset_review.jsonl"
    chunk = Chunk(raw_text="rough")
    chunk.provider = "gemini"
    chunk.model = "gemini-test"

    from uttate.addons.dataset_collection import add_dataset_candidate

    item = add_dataset_candidate(
        store,
        chunk,
        converted_text="converted",
        accepted_text="accepted",
        provider_type="local_ai",
    )

    assert item["provider"] == "gemini"
    assert item["external_api"] is True


def _item(
    item_id: str,
    status: str,
    *,
    raw_input: str,
    normalized_input: str = "",
    converted_text: str = "",
    accepted_text: str = "",
    edited_text: str = "",
    provider: str = "local_ai",
    model: str = "test-model",
    redactions: list[dict[str, object]] | None = None,
) -> DatasetItem:
    return {
        "id": f"ds_20260708_00000{item_id == 'two' and 2 or 1}",
        "chunk_id": item_id,
        "status": "adopted",
        "dataset_status": status,  # type: ignore[typeddict-item]
        "provider": provider,
        "model": model,
        "created_at": "2026-07-08T12:00:00+09:00",
        "raw_input": raw_input,
        "normalized_input": normalized_input or raw_input,
        "converted_text": converted_text or raw_input,
        "edited_text": edited_text,
        "accepted_text": accepted_text or converted_text or raw_input,
        "redactions": redactions or [],
        "external_api": provider in {"gemini", "openai"},
        "api_key": "secret",  # type: ignore[typeddict-unknown-key]
        "full_prompt": "secret prompt",  # type: ignore[typeddict-unknown-key]
        "raw_api_response": "secret response",  # type: ignore[typeddict-unknown-key]
    }
