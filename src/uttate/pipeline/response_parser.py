from __future__ import annotations

import json
from typing import Any

from uttate.models import JsonObject
from uttate.providers.base import Candidate, ProviderError, ProviderResult


def parse_provider_result(
    text: str,
    *,
    provider: str,
    model: str,
    candidate_count: int = 2,
    raw_response: str | None = None,
) -> ProviderResult:
    """Parse provider JSON into the small Project B result contract.

    LLM APIs still occasionally wrap JSON in markdown fences or explanatory text.
    The parser is deliberately tolerant about extraction, but strict about the final
    shape: broken candidates become a failed chunk instead of suspicious review text.
    """

    if candidate_count <= 0:
        raise ValueError("candidate_count must be positive.")

    decoded = _decode_json_object(text)
    candidates_raw = decoded.get("candidates")
    if not isinstance(candidates_raw, list) or not candidates_raw:
        raise ProviderError("Provider response must include at least one candidate.")

    candidates: list[Candidate] = []
    for index, value in enumerate(candidates_raw[:candidate_count], start=1):
        if not isinstance(value, dict):
            raise ProviderError(f"Candidate {index} must be an object.")
        label = value.get("label") if isinstance(value.get("label"), str) else f"candidate_{index}"
        text_value = value.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            raise ProviderError(f"Candidate {index} text must be a non-empty string.")
        candidates.append(Candidate(label.strip(), text_value.strip()))

    uncertain = _parse_uncertain(decoded.get("uncertain", []))
    return ProviderResult(
        candidates=tuple(candidates),
        uncertain=tuple(uncertain),
        provider=provider,
        model=model,
        raw_response=raw_response if raw_response is not None else text,
    )


def _decode_json_object(text: str) -> JsonObject:
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("Provider response text was empty.")

    for candidate in _json_candidates(text.strip()):
        try:
            decoded: Any = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    raise ProviderError("Provider response did not contain a valid JSON object.")


def _json_candidates(text: str) -> tuple[str, ...]:
    stripped = _strip_json_fence(text)
    extracted = _extract_first_json_object(stripped)
    if extracted == stripped:
        return (stripped,)
    return (stripped, extracted)


def _strip_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return text

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text


def _parse_uncertain(value: Any) -> list[JsonObject]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProviderError("Provider response uncertain must be an array.")

    uncertain: list[JsonObject] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ProviderError(f"Uncertain item {index} must be an object.")
        raw = item.get("raw", "")
        reason = item.get("reason", "")
        candidates = item.get("candidates", [])
        if (
            not isinstance(raw, str)
            or not isinstance(reason, str)
            or not isinstance(candidates, list)
        ):
            raise ProviderError(f"Uncertain item {index} has an invalid shape.")
        uncertain.append(
            {
                "raw": raw,
                "reason": reason,
                "candidates": [candidate for candidate in candidates if isinstance(candidate, str)],
            }
        )
    return uncertain
