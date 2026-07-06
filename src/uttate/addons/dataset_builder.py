from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

TaskName = Literal[
    "raw_to_literal",
    "raw_to_natural",
    "raw_to_both",
    "raw_to_kana",
    "kana_to_literal",
    "kana_to_natural",
    "kana_to_both",
]

ROMAJI_VOWELS = set("aeiouAEIOU")
KEY_NEIGHBORS: dict[str, str] = {
    "q": "wa",
    "w": "qase",
    "e": "wsdr",
    "r": "edft",
    "t": "rfgy",
    "y": "tghu",
    "u": "yhji",
    "i": "ujko",
    "o": "iklp",
    "p": "ol",
    "a": "qwsz",
    "s": "awedxz",
    "d": "serfcx",
    "f": "drtgvc",
    "g": "ftyhbv",
    "h": "gyujnb",
    "j": "huikmn",
    "k": "jiolm",
    "l": "kop",
    "z": "asx",
    "x": "zsdc",
    "c": "xdfv",
    "v": "cfgb",
    "b": "vghn",
    "n": "bhjm",
    "m": "njk",
}

ROMAJI_ALTERNATIONS: list[tuple[str, str]] = [
    ("shi", "si"),
    ("si", "shi"),
    ("chi", "ti"),
    ("ti", "chi"),
    ("tsu", "tu"),
    ("tu", "tsu"),
    ("fu", "hu"),
    ("hu", "fu"),
    ("ji", "zi"),
    ("zi", "ji"),
    ("ja", "zya"),
    ("ju", "zyu"),
    ("jo", "zyo"),
    ("zya", "ja"),
    ("zyu", "ju"),
    ("zyo", "jo"),
    ("sha", "sya"),
    ("shu", "syu"),
    ("sho", "syo"),
    ("sya", "sha"),
    ("syu", "shu"),
    ("syo", "sho"),
    ("cha", "tya"),
    ("chu", "tyu"),
    ("cho", "tyo"),
    ("tya", "cha"),
    ("tyu", "chu"),
    ("tyo", "cho"),
    ("wo", "o"),
    ("nn", "n"),
    ("ou", "o"),
    ("oo", "o"),
    ("ei", "e"),
]

KANA_NOISE_PAIRS: list[tuple[str, str]] = [
    ("づ", "ず"),
    ("ず", "づ"),
    ("じ", "ぢ"),
    ("ぢ", "じ"),
    ("を", "お"),
    ("へ", "え"),
    ("ー", ""),
]

DEFAULT_PROTECTED_TERMS = (
    "API,Gemini,OpenAI,Claude,ChatGPT,GitHub,Python,JavaScript,TypeScript,"
    "React,Vue,LLM,QLoRA,LoRA,IME,Obsidian,VSCode"
)

DEFAULT_SYSTEM_PROMPT = (
    "あなたはローマ字入力・英語混じり入力を、"
    "日本語の文として復元する変換エンジンです。"
    "入力の誤字、母音抜け、n/nnの揺れ、"
    "英語と日本語の混在を考慮してください。"
    "指示された形式だけで答えてください。"
)


@dataclass(frozen=True)
class SeedRecord:
    id: str
    raw: str
    kana: str
    literal: str
    natural: str


@dataclass(frozen=True)
class BuildConfig:
    variants_per_seed: int = 24
    seed: int = 42
    train_ratio: float = 0.90
    valid_ratio: float = 0.05
    test_ratio: float = 0.05
    include_kana_tasks: bool = False
    include_intermediate_task: bool = False
    max_noise_ops: int = 3
    min_input_chars: int = 4
    protected_terms: tuple[str, ...] = ()
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


def stable_id(*parts: str, length: int = 16) -> str:
    digest = hashlib.sha256("\u241f".join(parts).encode("utf-8")).hexdigest()
    return digest[:length]


def stable_int(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def parse_terms(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(term.strip() for term in raw.split(",") if term.strip())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                message = f"Invalid JSONL at {path}:{line_number}: {exc}"
                raise ValueError(message) from exc
    return rows


def load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def load_seed_records(path: Path) -> list[SeedRecord]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows = load_jsonl(path)
    elif suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, dict) and isinstance(raw.get("records"), list):
            rows = raw["records"]
        else:
            message = "JSON input must be a list or an object with records: [...]."
            raise ValueError(message)
    elif suffix == ".csv":
        rows = load_csv(path)
    else:
        raise ValueError("Input must be .jsonl, .json, or .csv")

    records: list[SeedRecord] = []
    required = ("raw", "kana", "literal", "natural")
    for index, row in enumerate(rows, 1):
        missing = [key for key in required if not str(row.get(key, "")).strip()]
        if missing:
            raise ValueError(f"Seed row {index} is missing required fields: {missing}")
        records.append(
            SeedRecord(
                id=str(row.get("id") or f"seed_{index:06d}"),
                raw=str(row["raw"]).strip(),
                kana=str(row["kana"]).strip(),
                literal=str(row["literal"]).strip(),
                natural=str(row["natural"]).strip(),
            )
        )
    return records


def protect_spans(text: str, terms: Sequence[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for term in sorted(set(terms), key=len, reverse=True):
        if not term:
            continue
        for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE):
            spans.append((match.start(), match.end()))

    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def in_spans(index: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in spans)


def eligible_indices(
    text: str,
    spans: Sequence[tuple[int, int]],
    predicate: Any,
) -> list[int]:
    return [
        index
        for index, character in enumerate(text)
        if not in_spans(index, spans) and predicate(character)
    ]


def maybe_strip_spaces(text: str, rng: random.Random, probability: float = 0.8) -> str:
    if " " in text and rng.random() < probability:
        return re.sub(r"\s+", "", text)
    return text


def random_case_noise(text: str, rng: random.Random) -> str:
    if rng.random() > 0.25:
        return text
    characters = list(text)
    positions = [
        index for index, character in enumerate(text) if character.isalpha() and character.isascii()
    ]
    if not positions:
        return text
    sample_size = min(len(positions), rng.randint(1, 3))
    for index in rng.sample(positions, k=sample_size):
        if rng.random() < 0.5:
            characters[index] = characters[index].upper()
        else:
            characters[index] = characters[index].lower()
    return "".join(characters)


def apply_romaji_alternation(text: str, rng: random.Random, protected_terms: Sequence[str]) -> str:
    spans = protect_spans(text, protected_terms)
    candidates: list[tuple[int, str, str]] = []
    lower_text = text.lower()
    for source, destination in ROMAJI_ALTERNATIONS:
        start = 0
        while True:
            position = lower_text.find(source, start)
            if position == -1:
                break
            edit_range = range(position, position + len(source))
            if not any(in_spans(index, spans) for index in edit_range):
                candidates.append((position, text[position : position + len(source)], destination))
            start = position + 1

    if not candidates:
        return text
    position, actual_source, destination = rng.choice(candidates)
    if actual_source.isupper():
        destination = destination.upper()
    return text[:position] + destination + text[position + len(actual_source) :]


def drop_vowel(text: str, rng: random.Random, protected_terms: Sequence[str]) -> str:
    spans = protect_spans(text, protected_terms)
    candidates = eligible_indices(text, spans, lambda character: character in ROMAJI_VOWELS)
    candidates = [index for index in candidates if len(text) >= 4 and 0 < index < len(text) - 1]
    if not candidates:
        return text
    index = rng.choice(candidates)
    return text[:index] + text[index + 1 :]


def delete_char(text: str, rng: random.Random, protected_terms: Sequence[str]) -> str:
    spans = protect_spans(text, protected_terms)
    candidates = eligible_indices(
        text,
        spans,
        lambda character: character.isascii() and character not in "\n\t",
    )
    if len(text) <= 3 or not candidates:
        return text
    index = rng.choice(candidates)
    return text[:index] + text[index + 1 :]


def duplicate_char(text: str, rng: random.Random, protected_terms: Sequence[str]) -> str:
    spans = protect_spans(text, protected_terms)
    candidates = eligible_indices(
        text,
        spans,
        lambda character: character.isascii() and character.isalnum(),
    )
    if not candidates:
        return text
    index = rng.choice(candidates)
    return text[:index] + text[index] + text[index:]


def transpose_adjacent(text: str, rng: random.Random, protected_terms: Sequence[str]) -> str:
    spans = protect_spans(text, protected_terms)
    candidates = [
        index
        for index in range(len(text) - 1)
        if not in_spans(index, spans)
        and not in_spans(index + 1, spans)
        and text[index].isascii()
        and text[index + 1].isascii()
        and text[index].isalnum()
        and text[index + 1].isalnum()
    ]
    if not candidates:
        return text
    index = rng.choice(candidates)
    characters = list(text)
    characters[index], characters[index + 1] = characters[index + 1], characters[index]
    return "".join(characters)


def keyboard_substitute(text: str, rng: random.Random, protected_terms: Sequence[str]) -> str:
    spans = protect_spans(text, protected_terms)
    candidates = eligible_indices(text, spans, lambda character: character.lower() in KEY_NEIGHBORS)
    if not candidates:
        return text
    index = rng.choice(candidates)
    character = text[index]
    new_character = rng.choice(KEY_NEIGHBORS[character.lower()])
    if character.isupper():
        new_character = new_character.upper()
    return text[:index] + new_character + text[index + 1 :]


def insert_random_ascii(text: str, rng: random.Random, protected_terms: Sequence[str]) -> str:
    spans = protect_spans(text, protected_terms)
    candidates = [index for index in range(len(text) + 1) if not in_spans(max(0, index - 1), spans)]
    if not candidates:
        return text
    index = rng.choice(candidates)
    character = rng.choice("aiueonmtsrkhyw")
    return text[:index] + character + text[index:]


def punctuation_noise(text: str, rng: random.Random) -> str:
    if rng.random() < 0.5:
        return text + rng.choice(["", "。", ".", "!", "?"])
    if rng.random() < 0.25 and len(text) > 8:
        index = rng.randint(2, len(text) - 2)
        return text[:index] + rng.choice([",", "、", " "]) + text[index:]
    return text


def mutate_raw(text: str, rng: random.Random, config: BuildConfig) -> str:
    mutators = [
        (0.22, drop_vowel),
        (0.14, delete_char),
        (0.14, duplicate_char),
        (0.12, transpose_adjacent),
        (0.12, keyboard_substitute),
        (0.08, insert_random_ascii),
        (0.18, apply_romaji_alternation),
    ]
    output = maybe_strip_spaces(text, rng)
    output = random_case_noise(output, rng)

    operations = rng.randint(1, max(1, config.max_noise_ops))
    for _ in range(operations):
        roll = rng.random()
        accumulated = 0.0
        for weight, mutator in mutators:
            accumulated += weight
            if roll <= accumulated:
                output = mutator(output, rng, config.protected_terms)
                break
    if rng.random() < 0.25:
        output = punctuation_noise(output, rng)
    return output


def mutate_kana(text: str, rng: random.Random) -> str:
    output = text
    if rng.random() < 0.35:
        source, destination = rng.choice(KANA_NOISE_PAIRS)
        if source in output:
            output = output.replace(source, destination, 1)
    if rng.random() < 0.2:
        output = re.sub(r"\s+", "", output)
    if rng.random() < 0.12 and len(output) > 6:
        index = rng.randint(1, len(output) - 2)
        output = output[:index] + rng.choice(["、", " "]) + output[index:]
    return output


def build_user_prompt(task: TaskName, input_text: str) -> str:
    if task == "raw_to_literal":
        return (
            "次の生データを、内容に忠実な"
            "漢字仮名交じり文に変換してください。\n"
            "誤字や母音抜けがあっても、意味を推定してください。\n"
            "出力は本文だけにしてください。\n\n"
            f"生データ: {input_text}"
        )
    if task == "raw_to_natural":
        return (
            "次の生データを、文脈から自然な日本語に整えてください。\n"
            "逐語変換に固執せず、明らかな誤変換・入力ミス・"
            "不自然な語順は直してください。\n"
            "出力は本文だけにしてください。\n\n"
            f"生データ: {input_text}"
        )
    if task == "raw_to_both":
        return (
            "次の生データを日本語に変換してください。\n"
            "literalには内容に忠実な変換後テキストAを、"
            "naturalには自然に整えた変換後テキストBを入れてください。\n"
            "出力はJSONだけにしてください。\n\n"
            f"生データ: {input_text}"
        )
    if task == "raw_to_kana":
        return (
            "次の生データを、英語かな混じりの"
            "日本語化テキストにしてください。\n"
            "漢字変換はせず、読みとして復元してください。\n"
            "出力は本文だけにしてください。\n\n"
            f"生データ: {input_text}"
        )
    if task == "kana_to_literal":
        return (
            "次の英語かな混じり文を、内容に忠実な"
            "漢字仮名交じり文に変換してください。\n"
            "出力は本文だけにしてください。\n\n"
            f"日本語化テキスト: {input_text}"
        )
    if task == "kana_to_natural":
        return (
            "次の英語かな混じり文を、自然な"
            "漢字仮名交じり文に整えてください。\n"
            "出力は本文だけにしてください。\n\n"
            f"日本語化テキスト: {input_text}"
        )
    if task == "kana_to_both":
        return (
            "次の英語かな混じり文を日本語に変換してください。\n"
            "literalには内容に忠実な変換後テキストAを、"
            "naturalには自然に整えた変換後テキストBを入れてください。\n"
            "出力はJSONだけにしてください。\n\n"
            f"日本語化テキスト: {input_text}"
        )
    raise ValueError(f"Unknown task: {task}")


def build_assistant_text(task: TaskName, record: SeedRecord) -> str:
    if task in {"raw_to_literal", "kana_to_literal"}:
        return record.literal
    if task in {"raw_to_natural", "kana_to_natural"}:
        return record.natural
    if task == "raw_to_kana":
        return record.kana
    if task in {"raw_to_both", "kana_to_both"}:
        return json.dumps(
            {"literal": record.literal, "natural": record.natural},
            ensure_ascii=False,
        )
    raise ValueError(f"Unknown task: {task}")


def make_chat_example(
    record: SeedRecord,
    task: TaskName,
    input_text: str,
    config: BuildConfig,
    variant_index: int,
    split: str,
    is_original: bool,
) -> dict[str, Any]:
    assistant_text = build_assistant_text(task, record)
    return {
        "id": stable_id(record.id, task, input_text, assistant_text),
        "messages": [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": build_user_prompt(task, input_text)},
            {"role": "assistant", "content": assistant_text},
        ],
        "meta": {
            "source_id": record.id,
            "task": task,
            "split": split,
            "variant_index": variant_index,
            "is_original_input": is_original,
            "raw": record.raw,
            "kana": record.kana,
            "literal": record.literal,
            "natural": record.natural,
        },
    }


def tasks_for_config(config: BuildConfig) -> list[TaskName]:
    tasks: list[TaskName] = ["raw_to_literal", "raw_to_natural", "raw_to_both"]
    if config.include_intermediate_task:
        tasks.append("raw_to_kana")
    if config.include_kana_tasks:
        tasks.extend(["kana_to_literal", "kana_to_natural", "kana_to_both"])
    return tasks


def split_seed_records(
    records: Sequence[SeedRecord],
    rng: random.Random,
    train_ratio: float,
    valid_ratio: float,
    test_ratio: float,
) -> dict[str, list[SeedRecord]]:
    if abs(train_ratio + valid_ratio + test_ratio - 1.0) > 1e-6:
        raise ValueError("train_ratio + valid_ratio + test_ratio must be 1.0")
    shuffled = list(records)
    rng.shuffle(shuffled)
    count = len(shuffled)
    if count == 0:
        return {"train": [], "valid": [], "test": []}
    if count < 3:
        return {"train": shuffled, "valid": [], "test": []}

    valid_count = int(count * valid_ratio)
    test_count = int(count * test_ratio)
    train_count = count - valid_count - test_count

    if valid_ratio > 0 and valid_count == 0:
        valid_count = 1
    if test_ratio > 0 and test_count == 0:
        test_count = 1

    while train_count + valid_count + test_count > count and train_count > 1:
        train_count -= 1
    while train_count + valid_count + test_count > count and valid_count > 0:
        valid_count -= 1
    while train_count + valid_count + test_count > count and test_count > 0:
        test_count -= 1
    while train_count + valid_count + test_count < count:
        train_count += 1

    return {
        "train": shuffled[:train_count],
        "valid": shuffled[train_count : train_count + valid_count],
        "test": shuffled[train_count + valid_count : train_count + valid_count + test_count],
    }


def generate_examples_for_record(
    record: SeedRecord,
    split: str,
    config: BuildConfig,
    rng: random.Random,
) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    seen_inputs: set[tuple[str, str]] = set()
    tasks = tasks_for_config(config)

    for task in tasks:
        base_input = record.kana if task.startswith("kana_") else record.raw
        examples.append(make_chat_example(record, task, base_input, config, 0, split, True))
        seen_inputs.add((task, base_input))

    attempts = 0
    max_attempts = config.variants_per_seed * len(tasks) * 20
    variant_index = 1
    while variant_index <= config.variants_per_seed and attempts < max_attempts:
        attempts += 1
        for task in tasks:
            input_text = (
                mutate_kana(record.kana, rng)
                if task.startswith("kana_")
                else mutate_raw(
                    record.raw,
                    rng,
                    config,
                )
            )
            input_text = input_text.strip()
            if len(input_text) < config.min_input_chars:
                continue
            key = (task, input_text)
            if key in seen_inputs:
                continue
            seen_inputs.add(key)
            examples.append(
                make_chat_example(record, task, input_text, config, variant_index, split, False)
            )
        variant_index += 1
    return examples


def dedupe_examples(examples: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for example in examples:
        key = str(example["id"])
        if key in seen:
            continue
        seen.add(key)
        output.append(example)
    return output


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def validate_records(records: Sequence[SeedRecord]) -> None:
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        duplicates = sorted({record_id for record_id in ids if ids.count(record_id) > 1})
        raise ValueError(f"Duplicate seed ids: {duplicates[:10]}")
    for record in records:
        if len(record.raw) < 3:
            raise ValueError(f"Seed {record.id}: raw is too short")


def build_dataset(input_path: Path, output_dir: Path, config: BuildConfig) -> dict[str, Any]:
    records = load_seed_records(input_path)
    validate_records(records)

    rng = random.Random(config.seed)
    splits = split_seed_records(
        records,
        rng,
        config.train_ratio,
        config.valid_ratio,
        config.test_ratio,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    split_counts: dict[str, int] = {}
    seed_counts = {split: len(split_records) for split, split_records in splits.items()}

    for split, split_records in splits.items():
        examples: list[dict[str, Any]] = []
        for record in split_records:
            record_rng = random.Random(config.seed + stable_int(record.id) + stable_int(split))
            examples.extend(generate_examples_for_record(record, split, config, record_rng))
        examples = dedupe_examples(examples)
        random.Random(config.seed + stable_int(split)).shuffle(examples)
        split_counts[split] = write_jsonl(output_dir / f"{split}.jsonl", examples)

    manifest = {
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "config": asdict(config),
        "seed_record_count": len(records),
        "seed_split_counts": seed_counts,
        "example_split_counts": split_counts,
        "tasks": tasks_for_config(config),
        "notes": [
            "Split is performed at seed-record level before augmentation to reduce leakage.",
            "Only input text is augmented; verified targets are copied from seed records.",
            "Use valid/test for sanity checks; prepare separate evaluation data.",
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build SFT datasets for Uttate Writer conversion models."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Seed data path: .jsonl, .json, or .csv",
    )
    parser.add_argument("--output", required=True, type=Path, help="Output directory")
    parser.add_argument("--variants-per-seed", type=int, default=24)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.90)
    parser.add_argument("--valid-ratio", type=float, default=0.05)
    parser.add_argument("--test-ratio", type=float, default=0.05)
    parser.add_argument("--include-kana-tasks", action="store_true")
    parser.add_argument("--include-intermediate-task", action="store_true")
    parser.add_argument("--max-noise-ops", type=int, default=3)
    parser.add_argument("--min-input-chars", type=int, default=4)
    parser.add_argument("--protected-terms", type=str, default=DEFAULT_PROTECTED_TERMS)
    parser.add_argument("--system-prompt", type=str, default=DEFAULT_SYSTEM_PROMPT)
    return parser


def config_from_args(args: argparse.Namespace) -> BuildConfig:
    return BuildConfig(
        variants_per_seed=args.variants_per_seed,
        seed=args.seed,
        train_ratio=args.train_ratio,
        valid_ratio=args.valid_ratio,
        test_ratio=args.test_ratio,
        include_kana_tasks=args.include_kana_tasks,
        include_intermediate_task=args.include_intermediate_task,
        max_noise_ops=args.max_noise_ops,
        min_input_chars=args.min_input_chars,
        protected_terms=parse_terms(args.protected_terms),
        system_prompt=args.system_prompt,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    manifest = build_dataset(args.input, args.output, config_from_args(args))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
