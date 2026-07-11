from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

from uttate.models import Chunk

DatasetStatus = Literal["excluded", "candidate", "whitelisted", "rejected", "exported"]
RedactionType = Literal["PERSON", "PLACE", "ORG", "DATE", "CONTACT", "WORK", "MASK", "CUSTOM"]
FieldSafety = Literal["unreviewed", "confirmed", "redacted"]

REVIEW_SCHEMA = "uttate.dataset.review"
REVIEW_SCHEMA_VERSION = 1
HISTORY_SCHEMA = "uttate.conversion.history"
HISTORY_SCHEMA_VERSION = 1

DATASET_STATUSES: frozenset[str] = frozenset(
    {"excluded", "candidate", "whitelisted", "rejected", "exported"}
)
REDACTION_TYPES: frozenset[str] = frozenset(
    {"PERSON", "PLACE", "ORG", "DATE", "CONTACT", "WORK", "MASK", "CUSTOM"}
)
REDACTABLE_FIELDS: tuple[str, ...] = (
    "raw_input",
    "normalized_input",
    "converted_text",
    "edited_text",
    "accepted_text",
)
FIELD_SAFETY_STATES: frozenset[str] = frozenset({"unreviewed", "confirmed", "redacted"})
# These are the stored fields that can become part of an exported training row.
# ``target_output`` is selected from the final three fields in priority order.
EXPORT_INPUT_FIELDS: tuple[str, ...] = ("raw_input", "normalized_input")
EXPORT_TARGET_FIELDS: tuple[str, ...] = ("edited_text", "accepted_text", "converted_text")
ID_PATTERN = re.compile(r"^ds_(?P<date>\d{8})_(?P<number>\d{6})$")
PLACEHOLDER_PATTERN = re.compile(r"^\[(PERSON|PLACE|ORG|DATE|CONTACT|WORK|MASK|CUSTOM)_(\d+)\]$")


class DatasetItem(TypedDict, total=False):
    schema: str
    schema_version: int
    id: str
    chunk_id: str
    status: str
    dataset_status: DatasetStatus
    provider: str
    model: str
    created_at: str
    raw_input: str
    normalized_input: str
    converted_text: str
    edited_text: str
    accepted_text: str
    redactions: list[dict[str, Any]]
    field_safety: dict[str, FieldSafety]
    external_api: bool
    exported_at: str


class DatasetExportSummary(TypedDict):
    whitelisted_count: int
    anonymized_count: int
    non_anonymized_count: int
    gemini_count: int
    openai_count: int
    local_ai_count: int
    provider_model_counts: dict[str, int]
    exported_count: int


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def append_conversion_history(store: Path, chunk: Chunk) -> None:
    """Persist an opt-in immutable conversion event separately from review data."""

    rows: list[dict[str, object]] = []
    if store.exists():
        for line_number, line in enumerate(store.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid conversion history at {store}:{line_number}") from error
            if not isinstance(row, dict) or row.get("schema") != HISTORY_SCHEMA:
                raise ValueError(f"Unexpected conversion history schema at {store}:{line_number}")
            rows.append({str(key): _json_safe(value) for key, value in row.items()})
    rows.append(
        {
            "schema": HISTORY_SCHEMA,
            "schema_version": HISTORY_SCHEMA_VERSION,
            "event_id": f"{chunk.id}:{chunk.updated_at:.6f}",
            "recorded_at": now_iso(),
            "chunk_id": chunk.id,
            "status": chunk.status.value,
            "raw_input": chunk.raw_text,
            "candidate_1": chunk.candidate_1 or "",
            "candidate_2": chunk.candidate_2 or "",
            "adopted_text": chunk.adopted_text or "",
            "provider": chunk.provider or "",
            "model": chunk.model or "",
            "error_message": chunk.error_message or "",
        }
    )
    _atomic_write_jsonl(store, rows)


def load_dataset_items(store: Path) -> list[DatasetItem]:
    if not store.exists():
        return []

    items: list[DatasetItem] = []
    row_kinds: set[str] = set()
    with store.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                message = f"Invalid dataset JSONL at {store}:{line_number}: {exc}"
                raise ValueError(message) from exc
            if not isinstance(row, dict):
                raise ValueError(f"Dataset row {line_number} must be a JSON object.")
            row_kinds.add(_review_row_kind(row, line_number))
            items.append(normalize_dataset_item(row))
    if len(row_kinds) > 1:
        raise ValueError(f"Mixed dataset review schemas in {store}. Refusing to rewrite the store.")
    return items


def save_dataset_items(store: Path, items: Iterable[DatasetItem]) -> None:
    normalized = [normalize_dataset_item(item) for item in items]
    _atomic_write_jsonl(store, normalized)


def add_dataset_candidate(
    store: Path,
    chunk: Chunk,
    *,
    converted_text: str,
    accepted_text: str,
    edited_text: str = "",
    provider_type: str = "",
) -> DatasetItem:
    items = load_dataset_items(store)
    item_id = generate_dataset_id(items)
    provider = chunk.provider or provider_type or ""
    item: DatasetItem = {
        "id": item_id,
        "chunk_id": chunk.id,
        "status": chunk.status.value,
        "dataset_status": "candidate",
        "provider": provider,
        "model": chunk.model or "",
        "created_at": _timestamp_to_iso(chunk.created_at),
        "raw_input": chunk.raw_text,
        "normalized_input": chunk.raw_text,
        "converted_text": converted_text,
        "edited_text": edited_text,
        "accepted_text": accepted_text,
        "redactions": [],
        "field_safety": _default_field_safety(),
        "external_api": provider in {"gemini", "openai"},
    }
    items.append(item)
    save_dataset_items(store, items)
    return item


def set_dataset_status(store: Path, item_id: str, status: DatasetStatus) -> DatasetItem:
    if status not in DATASET_STATUSES:
        raise ValueError(f"Unknown dataset status: {status}")
    items = load_dataset_items(store)
    item = _find_item(items, item_id)
    item["dataset_status"] = status
    save_dataset_items(store, items)
    return item


def set_dataset_field_safety(
    store: Path,
    item_id: str,
    *,
    field: str,
    safety: FieldSafety,
) -> DatasetItem:
    """Record a reviewer confirmation for a field that may be exported.

    ``confirmed`` is an explicit human assertion that the current field contains
    no identifying or sensitive content. ``redacted`` is reserved for the
    redaction workflow because it must be backed by complete replacements.
    """
    if field not in REDACTABLE_FIELDS:
        raise ValueError(f"Field cannot be marked for export safety: {field}")
    if safety not in FIELD_SAFETY_STATES:
        raise ValueError(f"Unknown field safety: {safety}")
    if safety == "redacted":
        raise ValueError("Use apply_dataset_redaction to mark a field redacted.")

    items = load_dataset_items(store)
    item = _find_item(items, item_id)
    field_safety = _normalize_field_safety(item.get("field_safety"))
    field_safety[field] = safety
    item["field_safety"] = field_safety
    save_dataset_items(store, items)
    return item


def apply_dataset_redaction(
    store: Path,
    item_id: str,
    *,
    target_field: str,
    start: int,
    end: int,
    redaction_type: RedactionType,
    confirmed_fields: Sequence[str] = (),
) -> DatasetItem:
    if redaction_type not in REDACTION_TYPES:
        raise ValueError(f"Unknown redaction type: {redaction_type}")
    if target_field not in REDACTABLE_FIELDS:
        raise ValueError(f"Field cannot be anonymized: {target_field}")
    if start < 0 or end <= start:
        raise ValueError("Redaction range must be a non-empty selection.")

    items = load_dataset_items(store)
    item = _find_item(items, item_id)
    text = str(item.get(target_field, ""))
    if end > len(text):
        raise ValueError("Redaction range is outside the target text.")

    original_text = text[start:end]
    if not original_text:
        raise ValueError("Redaction range must contain text.")

    placeholder = _next_placeholder(item, redaction_type)
    replacements = _build_redaction_replacements(
        item,
        target_field=target_field,
        start=start,
        end=end,
        original_text=original_text,
        placeholder=placeholder,
        confirmed_fields=confirmed_fields,
    )
    _apply_replacements(item, replacements)
    redactions = list(item.get("redactions", []))
    redactions.append(
        {
            "type": redaction_type,
            "placeholder": placeholder,
            "original_text": original_text,
            "target_field": target_field,
            "start": start,
            "end": end,
            "created_at": now_iso(),
            "replacements": replacements,
        }
    )
    item["redactions"] = redactions
    field_safety = _normalize_field_safety(item.get("field_safety"))
    for field in {str(replacement["field"]) for replacement in replacements}:
        field_safety[field] = (
            "redacted" if _field_has_complete_redactions(item, field) else "unreviewed"
        )
    item["field_safety"] = field_safety
    save_dataset_items(store, items)
    return item


def undo_last_dataset_redaction(store: Path, item_id: str) -> DatasetItem:
    items = load_dataset_items(store)
    item = _find_item(items, item_id)
    redactions = list(item.get("redactions", []))
    if not redactions:
        raise ValueError("No anonymization history to undo.")

    redaction = redactions.pop()
    replacements = redaction.get("replacements", [])
    if not isinstance(replacements, list):
        replacements = []
    for replacement in sorted(
        (entry for entry in replacements if isinstance(entry, dict)),
        key=lambda entry: (
            str(entry.get("field", "")),
            int(entry.get("placeholder_start", entry.get("start", 0))),
        ),
        reverse=True,
    ):
        field = str(replacement.get("field", ""))
        if field not in REDACTABLE_FIELDS:
            continue
        placeholder = str(replacement.get("placeholder", redaction.get("placeholder", "")))
        original_text = str(replacement.get("original_text", redaction.get("original_text", "")))
        current = str(item.get(field, ""))
        start = _int_value(replacement.get("placeholder_start"), -1)
        end = _int_value(replacement.get("placeholder_end"), -1)
        if 0 <= start < end <= len(current) and current[start:end] == placeholder:
            item[field] = current[:start] + original_text + current[end:]
            continue
        item[field] = current.replace(placeholder, original_text, 1)

    item["redactions"] = redactions
    field_safety = _normalize_field_safety(item.get("field_safety"))
    for field in REDACTABLE_FIELDS:
        if field_safety[field] == "redacted" and not _field_has_complete_redactions(item, field):
            field_safety[field] = "unreviewed"
    item["field_safety"] = field_safety
    save_dataset_items(store, items)
    return item


def export_whitelisted_dataset(
    store: Path,
    output: Path,
    *,
    include_exported: bool = False,
) -> int:
    items = load_dataset_items(store)
    selected = _exportable_items(items, include_exported=include_exported)
    unsafe = {
        item["id"]: _unsafe_export_fields(item) for item in selected if _unsafe_export_fields(item)
    }
    if unsafe:
        details = ", ".join(
            f"{item_id} ({', '.join(fields)})" for item_id, fields in unsafe.items()
        )
        raise ValueError(
            "Whitelisted items must have every exported field confirmed or fully "
            f"redacted before export: {details}"
        )

    _atomic_write_jsonl(output, [_export_item(item) for item in selected])

    if selected:
        exported_at = now_iso()
        for item in items:
            if item.get("dataset_status") == "whitelisted" or (
                include_exported and item.get("dataset_status") == "exported"
            ):
                item["dataset_status"] = "exported"
                item["exported_at"] = exported_at
        save_dataset_items(store, items)
    return len(selected)


def dataset_export_summary(
    store: Path,
    *,
    include_exported: bool = False,
) -> DatasetExportSummary:
    items = load_dataset_items(store)
    selected = _exportable_items(items, include_exported=include_exported)
    provider_model_counts: dict[str, int] = {}
    summary: DatasetExportSummary = {
        "whitelisted_count": len(selected),
        "anonymized_count": 0,
        "non_anonymized_count": 0,
        "gemini_count": 0,
        "openai_count": 0,
        "local_ai_count": 0,
        "provider_model_counts": provider_model_counts,
        "exported_count": sum(1 for item in items if item.get("dataset_status") == "exported"),
    }
    for item in selected:
        if not _unsafe_export_fields(item):
            summary["anonymized_count"] += 1
        else:
            summary["non_anonymized_count"] += 1
        provider = _provider_label(item)
        if provider == "gemini":
            summary["gemini_count"] += 1
        elif provider == "openai":
            summary["openai_count"] += 1
        else:
            summary["local_ai_count"] += 1
        model = str(item.get("model", "")).strip() or "model unknown"
        key = f"{provider} / {model}"
        provider_model_counts[key] = provider_model_counts.get(key, 0) + 1
    return summary


def normalize_dataset_item(row: dict[str, Any]) -> DatasetItem:
    item_id = str(row.get("id", "")).strip()
    if not item_id:
        raise ValueError("Dataset item is missing id.")
    dataset_status = str(row.get("dataset_status", "candidate"))
    if dataset_status not in DATASET_STATUSES:
        raise ValueError(f"Unknown dataset status: {dataset_status}")
    legacy_row = "schema" not in row and "schema_version" not in row
    item: DatasetItem = {
        "schema": REVIEW_SCHEMA,
        "schema_version": REVIEW_SCHEMA_VERSION,
        "id": item_id,
        "chunk_id": str(row.get("chunk_id", "")),
        "status": str(row.get("status", "")),
        "dataset_status": dataset_status,  # type: ignore[typeddict-item]
        "provider": str(row.get("provider", "")),
        "model": str(row.get("model", "")),
        "created_at": str(row.get("created_at", "")),
        "raw_input": str(row.get("raw_input", "")),
        "normalized_input": str(row.get("normalized_input", "")),
        "converted_text": str(row.get("converted_text", "")),
        "edited_text": str(row.get("edited_text", "")),
        "accepted_text": str(row.get("accepted_text", "")),
        "redactions": _redactions(row.get("redactions", [])),
        "external_api": bool(row.get("external_api", False)),
        "exported_at": str(row.get("exported_at", "")),
    }
    item["field_safety"] = _normalize_field_safety(
        row.get("field_safety"),
        legacy_item=item if legacy_row else None,
    )
    return item


def generate_dataset_id(items: Sequence[DatasetItem], *, when: datetime | None = None) -> str:
    today = (when or datetime.now().astimezone()).strftime("%Y%m%d")
    max_number = 0
    for item in items:
        match = ID_PATTERN.match(str(item.get("id", "")))
        if match and match.group("date") == today:
            max_number = max(max_number, int(match.group("number")))
    return f"ds_{today}_{max_number + 1:06d}"


def _find_item(items: Sequence[DatasetItem], item_id: str) -> DatasetItem:
    for item in items:
        if item["id"] == item_id:
            return item
    raise ValueError(f"Dataset item not found: {item_id}")


def _redactions(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    redactions: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            redactions.append({str(key): _json_safe(value) for key, value in item.items()})
    return redactions


def _review_row_kind(row: dict[str, Any], line_number: int) -> str:
    """Identify a row without silently accepting the curator format."""
    schema = row.get("schema")
    version = row.get("schema_version")
    if schema is not None or version is not None:
        if schema != REVIEW_SCHEMA or version != REVIEW_SCHEMA_VERSION:
            raise ValueError(
                f"Dataset row {line_number} is not {REVIEW_SCHEMA} v{REVIEW_SCHEMA_VERSION}."
            )
        return "review-v1"
    if {"raw", "kana", "literal", "natural"}.issubset(row):
        raise ValueError(
            f"Dataset row {line_number} is a curator candidate, not a dataset review item."
        )
    if "dataset_status" not in row or "raw_input" not in row:
        raise ValueError(f"Dataset row {line_number} has no recognizable review schema.")
    return "review-legacy"


def _default_field_safety() -> dict[str, FieldSafety]:
    return {field: "unreviewed" for field in REDACTABLE_FIELDS}


def _normalize_field_safety(
    raw: object,
    *,
    legacy_item: DatasetItem | None = None,
) -> dict[str, FieldSafety]:
    source = raw if isinstance(raw, dict) else {}
    safety: dict[str, FieldSafety] = {}
    for field in REDACTABLE_FIELDS:
        value = str(source.get(field, "unreviewed"))
        safety[field] = value if value in FIELD_SAFETY_STATES else "unreviewed"  # type: ignore[assignment]
    if legacy_item is not None and not source:
        # Old review rows had no safety marker. Only infer a redacted state when
        # the stored redaction evidence proves the original is absent and the
        # replacement placeholder remains in that exact field.
        for field in REDACTABLE_FIELDS:
            if _field_has_complete_redactions(legacy_item, field):
                safety[field] = "redacted"
    return safety


def _field_has_complete_redactions(item: DatasetItem, field: str) -> bool:
    text = str(item.get(field, ""))
    redactions = item.get("redactions", [])
    if not redactions:
        return False
    found_placeholder = False
    for redaction in redactions:
        original_text = str(redaction.get("original_text", ""))
        placeholder = str(redaction.get("placeholder", ""))
        if original_text and original_text in text:
            return False
        if placeholder and placeholder in text:
            found_placeholder = True
    return found_placeholder


def _export_source_fields(item: DatasetItem) -> tuple[str, ...]:
    target_field = next(
        (field for field in EXPORT_TARGET_FIELDS if str(item.get(field, "")).strip()),
        "converted_text",
    )
    return (*EXPORT_INPUT_FIELDS, target_field)


def _unsafe_export_fields(item: DatasetItem) -> list[str]:
    safety = _normalize_field_safety(item.get("field_safety"))
    unsafe: list[str] = []
    for field in _export_source_fields(item):
        state = safety[field]
        if state == "confirmed":
            continue
        if state == "redacted" and _field_has_complete_redactions(item, field):
            continue
        unsafe.append(field)
    return unsafe


def _atomic_write_jsonl(store: Path, rows: Iterable[dict[str, object]]) -> None:
    """Durably replace a local JSONL file without truncating the prior store."""
    store.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = store.parent / f".{store.name}.{uuid4().hex}.tmp"
    try:
        with temporary_path.open("x", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, store)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _next_placeholder(item: DatasetItem, redaction_type: RedactionType) -> str:
    max_number = 0
    for redaction in item.get("redactions", []):
        placeholder = str(redaction.get("placeholder", ""))
        match = PLACEHOLDER_PATTERN.match(placeholder)
        if match and match.group(1) == redaction_type:
            max_number = max(max_number, int(match.group(2)))
    return f"[{redaction_type}_{max_number + 1}]"


def _build_redaction_replacements(
    item: DatasetItem,
    *,
    target_field: str,
    start: int,
    end: int,
    original_text: str,
    placeholder: str,
    confirmed_fields: Sequence[str],
) -> list[dict[str, Any]]:
    replacements = [
        _replacement_entry(
            field=target_field,
            original_text=original_text,
            placeholder=placeholder,
            start=start,
            end=end,
            placeholder_start=start,
        )
    ]
    confirmed = {field for field in confirmed_fields if field in REDACTABLE_FIELDS}
    for field in REDACTABLE_FIELDS:
        if field == target_field:
            continue
        text = str(item.get(field, ""))
        matches = list(_match_ranges(text, original_text))
        if len(matches) == 1 or (field in confirmed and matches):
            replacements.extend(
                _replacement_entry(
                    field=field,
                    original_text=original_text,
                    placeholder=placeholder,
                    start=match_start,
                    end=match_end,
                    placeholder_start=match_start,
                )
                for match_start, match_end in matches
            )
    return replacements


def _apply_replacements(item: DatasetItem, replacements: list[dict[str, Any]]) -> None:
    by_field: dict[str, list[dict[str, Any]]] = {}
    for replacement in replacements:
        field = str(replacement.get("field", ""))
        by_field.setdefault(field, []).append(replacement)

    for field, field_replacements in by_field.items():
        text = str(item.get(field, ""))
        offset = 0
        for replacement in sorted(field_replacements, key=lambda entry: int(entry["start"])):
            start = int(replacement["start"])
            end = int(replacement["end"])
            placeholder = str(replacement["placeholder"])
            adjusted_start = start + offset
            adjusted_end = end + offset
            text = text[:adjusted_start] + placeholder + text[adjusted_end:]
            replacement["placeholder_start"] = adjusted_start
            replacement["placeholder_end"] = adjusted_start + len(placeholder)
            offset += len(placeholder) - (end - start)
        item[field] = text


def _replacement_entry(
    *,
    field: str,
    original_text: str,
    placeholder: str,
    start: int,
    end: int,
    placeholder_start: int,
) -> dict[str, Any]:
    return {
        "field": field,
        "original_text": original_text,
        "placeholder": placeholder,
        "start": start,
        "end": end,
        "placeholder_start": placeholder_start,
        "placeholder_end": placeholder_start + len(placeholder),
    }


def _match_ranges(text: str, needle: str) -> Iterable[tuple[int, int]]:
    if not needle:
        return
    position = text.find(needle)
    while position >= 0:
        yield position, position + len(needle)
        position = text.find(needle, position + len(needle))


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_safe(value: object) -> object:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _timestamp_to_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _export_item(item: DatasetItem) -> dict[str, object]:
    return {
        "raw_input": item["raw_input"],
        "normalized_input": item["normalized_input"],
        "target_output": _target_output(item),
        "redactions": _export_redactions(item),
        "provider": _provider_label(item),
        "model": str(item.get("model", "")),
        "created_at": item["created_at"],
        "source": "uttate_writer_manual_whitelist",
        "schema_version": 1,
    }


def _exportable_items(
    items: Sequence[DatasetItem],
    *,
    include_exported: bool = False,
) -> list[DatasetItem]:
    statuses = {"whitelisted", "exported"} if include_exported else {"whitelisted"}
    return [item for item in items if item.get("dataset_status") in statuses]


def _target_output(item: DatasetItem) -> str:
    for key in ("edited_text", "accepted_text", "converted_text"):
        value = str(item.get(key, "")).strip()
        if value:
            return value
    return ""


def _provider_label(item: DatasetItem) -> str:
    provider = str(item.get("provider", "")).strip().lower()
    if provider in {"gemini", "openai", "local_ai"}:
        return provider
    return "local_ai"


def _export_redactions(item: DatasetItem) -> list[dict[str, object]]:
    exported: list[dict[str, object]] = []
    for redaction in item.get("redactions", []):
        exported.append(
            {
                "type": str(redaction.get("type", "")),
                "placeholder": str(redaction.get("placeholder", "")),
                "target_field": str(redaction.get("target_field", "")),
                "start": _int_value(redaction.get("start"), -1),
                "end": _int_value(redaction.get("end"), -1),
                "created_at": str(redaction.get("created_at", "")),
            }
        )
    return exported
