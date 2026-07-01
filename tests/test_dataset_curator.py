import json
from pathlib import Path

import pytest

from uttate.addons.dataset_builder import load_seed_records
from uttate.addons.dataset_curator import (
    add_candidate,
    approve_candidate,
    check_store_risks,
    export_seeds,
    is_public_ready,
    load_candidates,
    reject_candidate,
)


def sample_texts(suffix: str = "") -> dict[str, str]:
    return {
        "raw": f"kyouhaAPIwotukattehenkannosikennwosuru{suffix}",
        "kana": f"きょうはAPIをつかってへんかんのしけんをする{suffix}",
        "literal": f"今日はAPIを使って変換の試験をする。{suffix}",
        "natural": f"今日はAPIを使って、変換のテストをする。{suffix}",
    }


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_add_candidate_creates_store_with_safe_defaults(tmp_path: Path) -> None:
    store = tmp_path / "nested" / "candidates.jsonl"

    candidate = add_candidate(store, **sample_texts(), candidate_id="cand_test_001")

    assert store.exists()
    assert candidate["id"] == "cand_test_001"
    assert candidate["status"] == "candidate"
    assert candidate["notes"] == ""
    assert all(value is False for value in candidate["checks"].values())
    assert load_candidates(store)[0]["raw"] == sample_texts()["raw"]


def test_add_candidate_rejects_duplicate_id(tmp_path: Path) -> None:
    store = tmp_path / "candidates.jsonl"
    add_candidate(store, **sample_texts(), candidate_id="same")

    with pytest.raises(ValueError, match="already exists"):
        add_candidate(store, **sample_texts("2"), candidate_id="same")


def test_approve_private_only_changes_status_only(tmp_path: Path) -> None:
    store = tmp_path / "candidates.jsonl"
    add_candidate(store, **sample_texts(), candidate_id="cand_private")

    candidate = approve_candidate(store, "cand_private", private_only=True)

    assert candidate["status"] == "approved"
    assert all(value is False for value in candidate["checks"].values())
    assert not is_public_ready(candidate)


def test_approve_public_safe_sets_all_checks(tmp_path: Path) -> None:
    store = tmp_path / "candidates.jsonl"
    add_candidate(store, **sample_texts(), candidate_id="cand_public")

    candidate = approve_candidate(store, "cand_public", public_safe=True)

    assert candidate["status"] == "approved"
    assert all(value is True for value in candidate["checks"].values())
    assert is_public_ready(candidate)


def test_reject_saves_status_and_notes(tmp_path: Path) -> None:
    store = tmp_path / "candidates.jsonl"
    add_candidate(store, **sample_texts(), candidate_id="cand_reject")

    candidate = reject_candidate(store, "cand_reject", notes="contains private project details")

    assert candidate["status"] == "rejected"
    assert candidate["notes"] == "contains private project details"


def test_public_export_only_writes_public_ready_approved_candidates(tmp_path: Path) -> None:
    store = tmp_path / "candidates.jsonl"
    output = tmp_path / "seeds.public.jsonl"
    add_candidate(store, **sample_texts(" public"), candidate_id="cand_public")
    add_candidate(store, **sample_texts(" private"), candidate_id="cand_private")
    add_candidate(store, **sample_texts(" rejected"), candidate_id="cand_rejected")
    approve_candidate(store, "cand_public", public_safe=True)
    approve_candidate(store, "cand_private", private_only=True)
    reject_candidate(store, "cand_rejected")

    count = export_seeds(store, output, mode="public")

    assert count == 1
    rows = read_jsonl(output)
    assert [row["id"] for row in rows] == ["cand_public"]
    assert set(rows[0]) == {"id", "raw", "kana", "literal", "natural"}


def test_private_export_writes_any_approved_candidate_but_not_rejected(tmp_path: Path) -> None:
    store = tmp_path / "candidates.jsonl"
    output = tmp_path / "seeds.private.jsonl"
    add_candidate(store, **sample_texts(" private"), candidate_id="cand_private")
    add_candidate(store, **sample_texts(" rejected"), candidate_id="cand_rejected")
    approve_candidate(store, "cand_private", private_only=True)
    reject_candidate(store, "cand_rejected")

    count = export_seeds(store, output, mode="private")

    assert count == 1
    assert [row["id"] for row in read_jsonl(output)] == ["cand_private"]


def test_dataset_builder_can_read_curator_export(tmp_path: Path) -> None:
    store = tmp_path / "candidates.jsonl"
    output = tmp_path / "seeds.public.jsonl"
    add_candidate(store, **sample_texts(), candidate_id="cand_builder")
    approve_candidate(store, "cand_builder", public_safe=True)
    export_seeds(store, output, mode="public")

    records = load_seed_records(output)

    assert len(records) == 1
    assert records[0].id == "cand_builder"
    assert records[0].natural == sample_texts()["natural"]


def test_check_detects_email_url_and_token_like_text(tmp_path: Path) -> None:
    store = tmp_path / "candidates.jsonl"
    add_candidate(
        store,
        candidate_id="cand_risky",
        raw="mail test@example.com token sk-abcdefghijklmnopqrstuvwx https://example.com",
        kana="メールのテスト",
        literal="メールのテストです。",
        natural="メールのテストです。",
    )

    candidates = check_store_risks(store)

    assert candidates[0]["risk_notes"] == ["email", "url", "token"]
    assert load_candidates(store)[0]["risk_notes"] == ["email", "url", "token"]
