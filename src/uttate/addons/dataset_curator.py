from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

Status = Literal["candidate", "approved", "rejected"]
ExportMode = Literal["public", "private"]

CURATOR_SCHEMA = "uttate.dataset.candidate"
CURATOR_SCHEMA_VERSION = 1

CHECK_KEYS = (
    "no_personal_info",
    "no_private_project",
    "no_sensitive_content",
    "public_safe",
)

SEED_FIELDS = ("id", "raw", "kana", "literal", "natural")
ID_PATTERN = re.compile(r"^cand_(?P<date>\d{8})_(?P<number>\d{6})$")

# The curator is a warning layer, not an automatic moderation system.
# These patterns intentionally err on the side of "show a human something to review".
RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "phone",
        re.compile(r"(?:\+?\d{1,3}[-\s]?)?(?:\(?\d{2,4}\)?[-\s]?)\d{2,4}[-\s]?\d{3,4}"),
    ),
    (
        "url",
        re.compile(r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE),
    ),
    (
        "token",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{12,})\b"
            r"|(?:api[_-]?key|access[_-]?token|secret|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_.-]{12,}",
            re.IGNORECASE,
        ),
    ),
    (
        "env_assignment",
        re.compile(r"(?m)^[A-Z][A-Z0-9_]{2,}\s*=\s*.+$"),
    ),
    (
        "postal_code",
        re.compile(r"\b\d{3}-\d{4}\b"),
    ),
    (
        "address_suffix",
        re.compile(r"[一-龥ぁ-んァ-ンA-Za-z0-9]+(?:県|市|区|町|丁目)"),
    ),
)


class Candidate(TypedDict, total=False):
    schema: str
    schema_version: int
    id: str
    status: Status
    raw: str
    kana: str
    literal: str
    natural: str
    checks: dict[str, bool]
    notes: str
    created_at: str
    updated_at: str
    source: str
    tags: list[str]
    risk_notes: list[str]


def now_iso() -> str:
    """Return a local timestamp so manually edited JSONL stays easy to inspect."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_checks() -> dict[str, bool]:
    return {key: False for key in CHECK_KEYS}


def load_candidates(store: Path) -> list[Candidate]:
    """Load curator candidates from JSONL. Missing stores are simply empty stores."""
    if not store.exists():
        return []

    candidates: list[Candidate] = []
    row_kinds: set[str] = set()
    with store.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                message = f"Invalid JSONL at {store}:{line_number}: {exc}"
                raise ValueError(message) from exc
            if not isinstance(row, dict):
                raise ValueError(f"Candidate row {line_number} must be a JSON object.")
            row_kinds.add(_candidate_row_kind(row, line_number))
            candidates.append(_normalize_candidate(row))
    if len(row_kinds) > 1:
        raise ValueError(f"Mixed candidate schemas in {store}. Refusing to rewrite the store.")
    return candidates


def save_candidates(store: Path, candidates: Iterable[Candidate]) -> None:
    """Durably replace the local candidate store."""
    _atomic_write_jsonl(store, [_normalize_candidate(candidate) for candidate in candidates])


def add_candidate(
    store: Path,
    *,
    raw: str,
    kana: str,
    literal: str,
    natural: str,
    candidate_id: str | None = None,
    source: str = "manual",
    tags: Sequence[str] | None = None,
) -> Candidate:
    """Append one candidate. New candidates are never export-ready by default."""
    candidates = load_candidates(store)
    used_ids = {candidate["id"] for candidate in candidates}
    new_id = candidate_id or generate_candidate_id(candidates)
    if new_id in used_ids:
        raise ValueError(f"Candidate id already exists: {new_id}")

    timestamp = now_iso()
    candidate: Candidate = {
        "id": new_id,
        "status": "candidate",
        "raw": raw,
        "kana": kana,
        "literal": literal,
        "natural": natural,
        "checks": default_checks(),
        "notes": "",
        "created_at": timestamp,
        "updated_at": timestamp,
        "source": source,
        "tags": list(tags or ()),
        "risk_notes": [],
    }
    candidates.append(candidate)
    save_candidates(store, candidates)
    return candidate


def approve_candidate(
    store: Path,
    candidate_id: str,
    *,
    public_safe: bool = False,
    private_only: bool = False,
) -> Candidate:
    """Approve a candidate for private use, or for public use when checks are explicit."""
    if public_safe == private_only:
        raise ValueError("Choose exactly one of public_safe or private_only.")

    candidates = load_candidates(store)
    candidate = _find_candidate(candidates, candidate_id)
    candidate["status"] = "approved"
    if public_safe:
        candidate["checks"] = {key: True for key in CHECK_KEYS}
    else:
        candidate["checks"] = _normalize_checks(candidate.get("checks", {}))
    candidate["updated_at"] = now_iso()
    save_candidates(store, candidates)
    return candidate


def reject_candidate(store: Path, candidate_id: str, *, notes: str | None = None) -> Candidate:
    """Reject a candidate. Rejected candidates are never exported."""
    candidates = load_candidates(store)
    candidate = _find_candidate(candidates, candidate_id)
    candidate["status"] = "rejected"
    if notes is not None:
        candidate["notes"] = notes
    candidate["updated_at"] = now_iso()
    save_candidates(store, candidates)
    return candidate


def export_seeds(store: Path, output: Path, *, mode: ExportMode) -> int:
    """Export only whitelisted records in the seed format read by dataset_builder."""
    candidates = load_candidates(store)
    if mode == "public":
        selected = [candidate for candidate in candidates if is_public_ready(candidate)]
    elif mode == "private":
        selected = [candidate for candidate in candidates if _is_private_ready(candidate)]
    else:
        raise ValueError(f"Unknown export mode: {mode}")

    _atomic_write_jsonl(
        output,
        [{field: candidate[field] for field in SEED_FIELDS} for candidate in selected],
    )
    return len(selected)


def is_public_ready(candidate: Candidate) -> bool:
    checks = _normalize_checks(candidate.get("checks", {}))
    return candidate.get("status") == "approved" and all(checks[key] for key in CHECK_KEYS)


def check_candidate_risks(candidate: Candidate) -> list[str]:
    """Return risk labels found across candidate text without exposing matched secrets."""
    text_fields = ("raw", "kana", "literal", "natural")
    haystack = "\n".join(str(candidate.get(field, "")) for field in text_fields)
    notes: list[str] = []
    for label, pattern in RISK_PATTERNS:
        if pattern.search(haystack):
            notes.append(label)
    return notes


def check_store_risks(store: Path) -> list[Candidate]:
    """Run the MVP risk scanner and persist labels into risk_notes."""
    candidates = load_candidates(store)
    timestamp = now_iso()
    for candidate in candidates:
        candidate["risk_notes"] = check_candidate_risks(candidate)
        candidate["updated_at"] = timestamp
    save_candidates(store, candidates)
    return candidates


def generate_candidate_id(candidates: Sequence[Candidate], *, when: datetime | None = None) -> str:
    today = (when or datetime.now().astimezone()).strftime("%Y%m%d")
    max_number = 0
    for candidate in candidates:
        match = ID_PATTERN.match(str(candidate.get("id", "")))
        if match and match.group("date") == today:
            max_number = max(max_number, int(match.group("number")))
    return f"cand_{today}_{max_number + 1:06d}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Curate Uttate Writer dataset candidates.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add one candidate to a JSONL store.")
    add.add_argument("--store", required=True, type=Path)
    add.add_argument("--id", dest="candidate_id")
    add.add_argument("--raw", required=True)
    add.add_argument("--kana", required=True)
    add.add_argument("--literal", required=True)
    add.add_argument("--natural", required=True)
    add.add_argument("--source", default="manual")
    add.add_argument("--tag", dest="tags", action="append", default=[])

    list_parser = subparsers.add_parser("list", help="List candidates.")
    list_parser.add_argument("--store", required=True, type=Path)

    approve = subparsers.add_parser("approve", help="Approve a candidate.")
    approve.add_argument("--store", required=True, type=Path)
    approve.add_argument("--id", dest="candidate_id", required=True)
    approve_mode = approve.add_mutually_exclusive_group(required=True)
    approve_mode.add_argument("--public-safe", action="store_true")
    approve_mode.add_argument("--private-only", action="store_true")

    reject = subparsers.add_parser("reject", help="Reject a candidate.")
    reject.add_argument("--store", required=True, type=Path)
    reject.add_argument("--id", dest="candidate_id", required=True)
    reject.add_argument("--notes")

    export = subparsers.add_parser("export", help="Export approved candidates as seed JSONL.")
    export.add_argument("--store", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--mode", choices=("public", "private"), required=True)

    check = subparsers.add_parser("check", help="Run regex-based safety warnings.")
    check.add_argument("--store", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return _run_command(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run_command(args: argparse.Namespace) -> int:
    if args.command == "add":
        candidate = add_candidate(
            args.store,
            raw=args.raw,
            kana=args.kana,
            literal=args.literal,
            natural=args.natural,
            candidate_id=args.candidate_id,
            source=args.source,
            tags=args.tags,
        )
        print(candidate["id"])
        return 0

    if args.command == "list":
        _print_candidate_list(load_candidates(args.store))
        return 0

    if args.command == "approve":
        candidate = approve_candidate(
            args.store,
            args.candidate_id,
            public_safe=args.public_safe,
            private_only=args.private_only,
        )
        print(f"approved {candidate['id']}")
        return 0

    if args.command == "reject":
        candidate = reject_candidate(args.store, args.candidate_id, notes=args.notes)
        print(f"rejected {candidate['id']}")
        return 0

    if args.command == "export":
        count = export_seeds(args.store, args.output, mode=args.mode)
        print(f"exported {count} seed(s) to {args.output}")
        return 0

    if args.command == "check":
        candidates = check_store_risks(args.store)
        for candidate in candidates:
            notes = candidate.get("risk_notes", [])
            suffix = ", ".join(notes) if notes else "ok"
            print(f"{candidate['id']}\t{suffix}")
        return 0

    raise ValueError(f"Unknown command: {args.command}")


def _normalize_candidate(row: dict[str, Any]) -> Candidate:
    required = ("id", "status", "raw", "kana", "literal", "natural")
    missing = [field for field in required if not str(row.get(field, "")).strip()]
    if missing:
        raise ValueError(f"Candidate is missing required fields: {missing}")

    status = str(row["status"])
    if status not in {"candidate", "approved", "rejected"}:
        raise ValueError(f"Unknown candidate status: {status}")

    candidate: Candidate = {
        "schema": CURATOR_SCHEMA,
        "schema_version": CURATOR_SCHEMA_VERSION,
        "id": str(row["id"]),
        "status": status,  # type: ignore[typeddict-item]
        "raw": str(row["raw"]),
        "kana": str(row["kana"]),
        "literal": str(row["literal"]),
        "natural": str(row["natural"]),
        "checks": _normalize_checks(row.get("checks", {})),
        "notes": str(row.get("notes", "")),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
        "source": str(row.get("source", "manual")),
        "tags": _string_list(row.get("tags", [])),
        "risk_notes": _string_list(row.get("risk_notes", [])),
    }
    return candidate


def _candidate_row_kind(row: dict[str, Any], line_number: int) -> str:
    """Validate the store format before a write can replace it."""
    schema = row.get("schema")
    version = row.get("schema_version")
    if schema is not None or version is not None:
        if schema != CURATOR_SCHEMA or version != CURATOR_SCHEMA_VERSION:
            raise ValueError(
                f"Candidate row {line_number} is not {CURATOR_SCHEMA} v{CURATOR_SCHEMA_VERSION}."
            )
        return "candidate-v1"
    if "dataset_status" in row or "raw_input" in row:
        raise ValueError(
            f"Candidate row {line_number} is a dataset review item, not a curator candidate."
        )
    required = {"id", "status", "raw", "kana", "literal", "natural"}
    if not required.issubset(row):
        raise ValueError(f"Candidate row {line_number} has no recognizable candidate schema.")
    return "candidate-legacy"


def _atomic_write_jsonl(store: Path, rows: Iterable[dict[str, object]]) -> None:
    """Durably replace a local JSONL file without first truncating it."""
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


def _normalize_checks(raw: object) -> dict[str, bool]:
    if not isinstance(raw, dict):
        raw = {}
    return {key: bool(raw.get(key, False)) for key in CHECK_KEYS}


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _find_candidate(candidates: Sequence[Candidate], candidate_id: str) -> Candidate:
    for candidate in candidates:
        if candidate["id"] == candidate_id:
            return candidate
    raise ValueError(f"Candidate not found: {candidate_id}")


def _is_private_ready(candidate: Candidate) -> bool:
    return candidate.get("status") == "approved"


def _print_candidate_list(candidates: Sequence[Candidate]) -> None:
    print("id\tstatus\tpublic_ready\traw_preview\tnatural_preview")
    for candidate in candidates:
        print(
            "\t".join(
                [
                    candidate["id"],
                    candidate["status"],
                    "yes" if is_public_ready(candidate) else "no",
                    _preview(candidate["raw"]),
                    _preview(candidate["natural"]),
                ]
            )
        )


def _preview(text: str, *, limit: int = 32) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
