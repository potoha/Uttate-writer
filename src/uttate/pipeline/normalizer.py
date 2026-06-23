from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Any

from uttate.models import JsonObject
from uttate.providers.base import ConversionResult, LLMProvider

READING_NORMALIZATION_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "normalized": {"type": "string", "minLength": 1},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "reading": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "kana",
                            "english",
                            "name_like",
                            "unknown",
                            "symbol",
                            "particle",
                            "verb",
                            "noun",
                        ],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["raw", "reading", "type", "confidence"],
                "additionalProperties": False,
            },
        },
        "uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["raw", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["normalized", "segments", "uncertain"],
    "additionalProperties": False,
}

_SEGMENT_TYPES = {
    "kana",
    "english",
    "name_like",
    "unknown",
    "symbol",
    "particle",
    "verb",
    "noun",
}


@dataclass(frozen=True, slots=True)
class ReadingNormalizationResult:
    normalized: str
    segments: tuple[JsonObject, ...]
    uncertain: tuple[JsonObject, ...]


class ReadingNormalizer:
    def __init__(self, provider: LLMProvider, *, system_prompt: str | None = None) -> None:
        self.provider = provider
        self.system_prompt = system_prompt or _load_system_prompt()

    def normalize(self, raw_text: str) -> ReadingNormalizationResult:
        if not raw_text.strip():
            raise ValueError("raw_text must not be empty.")
        response = self.provider.complete_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": raw_text},
            ],
            READING_NORMALIZATION_SCHEMA,
        )
        return _validate_response(response)


class ReadingNormalizationProvider:
    """Adapt Stage 1 to the UI queue while later pipeline stages remain absent."""

    def __init__(self, normalizer: ReadingNormalizer) -> None:
        self.normalizer = normalizer

    def convert(self, raw_text: str) -> ConversionResult:
        result = self.normalizer.normalize(raw_text)
        return ConversionResult(
            normalized=result.normalized,
            segments=result.segments,
            uncertain=result.uncertain,
        )


def _load_system_prompt() -> str:
    return (
        resources.files("uttate.prompts")
        .joinpath("reading_normalizer.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def _validate_response(response: JsonObject) -> ReadingNormalizationResult:
    normalized = response.get("normalized")
    if not isinstance(normalized, str) or not normalized.strip():
        raise ValueError("Stage 1 response.normalized must be a non-empty string.")

    segments_raw = response.get("segments")
    if not isinstance(segments_raw, list):
        raise ValueError("Stage 1 response.segments must be an array.")
    segments = tuple(_validate_segment(item, index) for index, item in enumerate(segments_raw))

    uncertain_raw = response.get("uncertain")
    if not isinstance(uncertain_raw, list):
        raise ValueError("Stage 1 response.uncertain must be an array.")
    uncertain = tuple(
        _validate_uncertainty(item, index) for index, item in enumerate(uncertain_raw)
    )
    return ReadingNormalizationResult(normalized, segments, uncertain)


def _validate_segment(value: Any, index: int) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"Stage 1 segment {index} must be an object.")
    raw = _required_string(value, "raw", f"segment {index}")
    reading = _required_string(value, "reading", f"segment {index}")
    segment_type = _required_string(value, "type", f"segment {index}")
    if segment_type not in _SEGMENT_TYPES:
        raise ValueError(f"Stage 1 segment {index} has an unsupported type.")
    confidence = value.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not 0 <= confidence <= 1
    ):
        raise ValueError(f"Stage 1 segment {index} confidence must be between 0 and 1.")
    return {
        "raw": raw,
        "reading": reading,
        "type": segment_type,
        "confidence": float(confidence),
    }


def _validate_uncertainty(value: Any, index: int) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"Stage 1 uncertainty {index} must be an object.")
    return {
        "raw": _required_string(value, "raw", f"uncertainty {index}"),
        "reason": _required_string(value, "reason", f"uncertainty {index}"),
    }


def _required_string(value: dict[str, Any], key: str, location: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise ValueError(f"Stage 1 {location}.{key} must be a string.")
    return result
