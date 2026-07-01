import json
from pathlib import Path

import pytest

from uttate.addons.dataset_builder import BuildConfig, build_dataset, load_seed_records


def write_seed_file(path: Path) -> None:
    rows = [
        {
            "id": "ex001",
            "raw": "kyouhaAPIwotukattehenkannosikennwosuru",
            "kana": "きょうはAPIをつかってへんかんのしけんをする",
            "literal": "今日はAPIを使って変換の試験をする。",
            "natural": "今日はAPIを使って、変換のテストをする。",
        },
        {
            "id": "ex002",
            "raw": "GeminiAPIdenihongoninaosu",
            "kana": "Gemini APIでにほんごになおす",
            "literal": "Gemini APIで日本語に直す。",
            "natural": "Gemini APIを使って日本語に直す。",
        },
        {
            "id": "ex003",
            "raw": "reviewmodehaenterdesyouninsuru",
            "kana": "review modeはenterでしょうにんする",
            "literal": "review modeはEnterで承認する。",
            "natural": "ReviewモードではEnterで承認する。",
        },
    ]
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_load_seed_records_accepts_jsonl(tmp_path: Path) -> None:
    input_path = tmp_path / "seeds.jsonl"
    write_seed_file(input_path)

    records = load_seed_records(input_path)

    assert [record.id for record in records] == ["ex001", "ex002", "ex003"]
    assert records[0].literal == "今日はAPIを使って変換の試験をする。"


def test_build_dataset_writes_chatml_splits_without_seed_leakage(tmp_path: Path) -> None:
    input_path = tmp_path / "seeds.jsonl"
    output_dir = tmp_path / "dataset"
    write_seed_file(input_path)

    manifest = build_dataset(
        input_path,
        output_dir,
        BuildConfig(
            variants_per_seed=2,
            train_ratio=0.5,
            valid_ratio=0.25,
            test_ratio=0.25,
            include_kana_tasks=True,
            include_intermediate_task=True,
            protected_terms=("API", "Gemini"),
        ),
    )

    assert (output_dir / "train.jsonl").exists()
    assert (output_dir / "valid.jsonl").exists()
    assert (output_dir / "test.jsonl").exists()
    assert (output_dir / "manifest.json").exists()
    assert manifest["seed_record_count"] == 3
    assert "raw_to_kana" in manifest["tasks"]
    assert "kana_to_natural" in manifest["tasks"]

    split_source_ids = {}
    for split in ("train", "valid", "test"):
        examples = read_jsonl(output_dir / f"{split}.jsonl")
        assert examples
        split_source_ids[split] = {example["meta"]["source_id"] for example in examples}
        assert all(example["messages"][0]["role"] == "system" for example in examples)
        assert all(example["messages"][-1]["role"] == "assistant" for example in examples)

    assert split_source_ids["train"].isdisjoint(split_source_ids["valid"])
    assert split_source_ids["train"].isdisjoint(split_source_ids["test"])
    assert split_source_ids["valid"].isdisjoint(split_source_ids["test"])


def test_build_dataset_rejects_duplicate_ids(tmp_path: Path) -> None:
    input_path = tmp_path / "seeds.jsonl"
    duplicate = {
        "id": "same",
        "raw": "kyouhatestwosuru",
        "kana": "きょうはtestをする",
        "literal": "今日はtestをする。",
        "natural": "今日はテストをする。",
    }
    input_path.write_text(
        json.dumps(duplicate, ensure_ascii=False)
        + "\n"
        + json.dumps(duplicate, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate seed ids"):
        build_dataset(input_path, tmp_path / "out", BuildConfig())
