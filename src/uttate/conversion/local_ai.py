from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from importlib import resources
from typing import Any, Protocol

from uttate.input_rules import MaskedProtectedInput, ProtectedMask, mask_protected_input
from uttate.models import JsonObject
from uttate.providers.base import Candidate, ProviderResult

READING_NORMALIZATION_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "source_echo": {"type": "string"},
        "normalized": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Faithful reading only. Never introduce kanji, punctuation, words, or meanings "
                "that are absent from original_raw."
            ),
        },
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "reading": {
                        "type": "string",
                        "description": (
                            "Reading of this raw span only; no translation, paraphrase, "
                            "or added text."
                        ),
                    },
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
    "required": ["source_echo", "normalized", "segments", "uncertain"],
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

_PARTICLE_READINGS = {
    "ha": "は",
    "wa": "は",
    "wo": "を",
    "e": "へ",
    "de": "で",
    "no": "の",
    "ni": "に",
    "to": "と",
    "ga": "が",
    "mo": "も",
    "kara": "から",
    "made": "まで",
    "yori": "より",
}

_ROMAJI_TOKEN_PATTERN = re.compile(r"[A-Za-z]+")
_ROMAJI_SYLLABLES = tuple(
    sorted(
        {
            "kya",
            "kyu",
            "kyo",
            "sha",
            "shu",
            "sho",
            "cha",
            "chu",
            "cho",
            "nya",
            "nyu",
            "nyo",
            "hya",
            "hyu",
            "hyo",
            "mya",
            "myu",
            "myo",
            "rya",
            "ryu",
            "ryo",
            "gya",
            "gyu",
            "gyo",
            "ja",
            "ju",
            "jo",
            "bya",
            "byu",
            "byo",
            "pya",
            "pyu",
            "pyo",
            "tsa",
            "tsi",
            "tse",
            "tso",
            "shi",
            "chi",
            "tsu",
            "fu",
            "ji",
            "ka",
            "ki",
            "ku",
            "ke",
            "ko",
            "sa",
            "su",
            "se",
            "so",
            "ta",
            "te",
            "to",
            "na",
            "ni",
            "nu",
            "ne",
            "no",
            "ha",
            "hi",
            "he",
            "ho",
            "ma",
            "mi",
            "mu",
            "me",
            "mo",
            "ya",
            "yu",
            "yo",
            "ra",
            "ri",
            "ru",
            "re",
            "ro",
            "wa",
            "wo",
            "ga",
            "gi",
            "gu",
            "ge",
            "go",
            "za",
            "zu",
            "ze",
            "zo",
            "da",
            "de",
            "do",
            "ba",
            "bi",
            "bu",
            "be",
            "bo",
            "pa",
            "pi",
            "pu",
            "pe",
            "po",
            "va",
            "vi",
            "vu",
            "ve",
            "vo",
            "a",
            "i",
            "u",
            "e",
            "o",
        },
        key=len,
        reverse=True,
    )
)

_ROMAJI_TO_HIRAGANA = {
    "kya": "きゃ",
    "kyu": "きゅ",
    "kyo": "きょ",
    "sha": "しゃ",
    "shu": "しゅ",
    "sho": "しょ",
    "cha": "ちゃ",
    "chu": "ちゅ",
    "cho": "ちょ",
    "nya": "にゃ",
    "nyu": "にゅ",
    "nyo": "にょ",
    "hya": "ひゃ",
    "hyu": "ひゅ",
    "hyo": "ひょ",
    "mya": "みゃ",
    "myu": "みゅ",
    "myo": "みょ",
    "rya": "りゃ",
    "ryu": "りゅ",
    "ryo": "りょ",
    "gya": "ぎゃ",
    "gyu": "ぎゅ",
    "gyo": "ぎょ",
    "ja": "じゃ",
    "ju": "じゅ",
    "jo": "じょ",
    "bya": "びゃ",
    "byu": "びゅ",
    "byo": "びょ",
    "pya": "ぴゃ",
    "pyu": "ぴゅ",
    "pyo": "ぴょ",
    "tsa": "つぁ",
    "tsi": "つぃ",
    "tse": "つぇ",
    "tso": "つぉ",
    "shi": "し",
    "chi": "ち",
    "tsu": "つ",
    "fu": "ふ",
    "ji": "じ",
    "ka": "か",
    "ki": "き",
    "ku": "く",
    "ke": "け",
    "ko": "こ",
    "sa": "さ",
    "su": "す",
    "se": "せ",
    "so": "そ",
    "ta": "た",
    "te": "て",
    "to": "と",
    "na": "な",
    "ni": "に",
    "nu": "ぬ",
    "ne": "ね",
    "no": "の",
    "ha": "は",
    "hi": "ひ",
    "he": "へ",
    "ho": "ほ",
    "ma": "ま",
    "mi": "み",
    "mu": "む",
    "me": "め",
    "mo": "も",
    "ya": "や",
    "yu": "ゆ",
    "yo": "よ",
    "ra": "ら",
    "ri": "り",
    "ru": "る",
    "re": "れ",
    "ro": "ろ",
    "wa": "わ",
    "wo": "を",
    "ga": "が",
    "gi": "ぎ",
    "gu": "ぐ",
    "ge": "げ",
    "go": "ご",
    "za": "ざ",
    "zu": "ず",
    "ze": "ぜ",
    "zo": "ぞ",
    "da": "だ",
    "de": "で",
    "do": "ど",
    "ba": "ば",
    "bi": "び",
    "bu": "ぶ",
    "be": "べ",
    "bo": "ぼ",
    "pa": "ぱ",
    "pi": "ぴ",
    "pu": "ぷ",
    "pe": "ぺ",
    "po": "ぽ",
    "va": "ゔぁ",
    "vi": "ゔぃ",
    "vu": "ゔ",
    "ve": "ゔぇ",
    "vo": "ゔぉ",
    "a": "あ",
    "i": "い",
    "u": "う",
    "e": "え",
    "o": "お",
}


@dataclass(frozen=True, slots=True)
class ReadingNormalizationResult:
    normalized: str
    segments: tuple[JsonObject, ...]
    uncertain: tuple[JsonObject, ...]


@dataclass(frozen=True, slots=True)
class PreparedLocalAIInput:
    masked: MaskedProtectedInput
    boundary_segments: tuple[JsonObject, ...]


class LocalAILLMProvider(Protocol):
    """Structured JSON boundary used by the main-derived local AI normalizer."""

    def complete_json(
        self,
        messages: list[JsonObject],
        schema: JsonObject | None = None,
    ) -> JsonObject:
        """Complete a chat request and return one decoded JSON object."""
        ...


class ReadingNormalizer:
    def __init__(
        self,
        provider: LocalAILLMProvider,
        *,
        system_prompt: str | None = None,
        max_validation_attempts: int = 2,
    ) -> None:
        if max_validation_attempts <= 0:
            raise ValueError("max_validation_attempts must be positive.")
        self.provider = provider
        self.system_prompt = system_prompt or load_default_system_prompt()
        self.max_validation_attempts = max_validation_attempts

    def normalize(self, raw_text: str) -> ReadingNormalizationResult:
        if not raw_text.strip():
            raise ValueError("raw_text must not be empty.")
        prepared = _prepare_local_ai_input(raw_text)
        model_text = prepared.masked.text
        messages: list[JsonObject] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": _input_payload(prepared)},
        ]
        last_error: ValueError | None = None
        for attempt in range(self.max_validation_attempts):
            response = self.provider.complete_json(messages, READING_NORMALIZATION_SCHEMA)
            response = _apply_required_readings(response, model_text)
            try:
                result = _validate_response(response, model_text)
                return _restore_masked_result(result, prepared.masked)
            except ValueError as error:
                last_error = error
                if attempt + 1 == self.max_validation_attempts:
                    break
                messages.extend(
                    [
                        {
                            "role": "assistant",
                            "content": json.dumps(response, ensure_ascii=False),
                        },
                        {
                            "role": "user",
                            "content": _repair_payload(prepared, str(error)),
                        },
                    ]
                )
        raise ValueError(
            "Stage 1 response failed fidelity validation after "
            f"{self.max_validation_attempts} attempt(s): {last_error}"
        ) from last_error


class ReadingNormalizationProvider:
    """Adapt Stage 1 to the UI queue while later pipeline stages remain absent."""

    def __init__(self, normalizer: ReadingNormalizer) -> None:
        self.normalizer = normalizer

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        del previous_context
        if candidate_count <= 0:
            raise ValueError("candidate_count must be positive.")
        result = self.normalizer.normalize(raw_text)
        candidates = (Candidate("faithful_reading", result.normalized),)[:candidate_count]
        return ProviderResult(
            candidates=candidates,
            uncertain=result.uncertain,
            provider="local_ai",
        )


def load_default_system_prompt() -> str:
    return (
        resources.files("uttate.prompts")
        .joinpath("reading_normalizer.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def _validate_response(response: JsonObject, raw_text: str) -> ReadingNormalizationResult:
    source_echo = response.get("source_echo")
    if source_echo != raw_text:
        raise ValueError("Stage 1 response.source_echo did not exactly match original_raw.")

    normalized = response.get("normalized")
    if not isinstance(normalized, str) or not normalized.strip():
        raise ValueError("Stage 1 response.normalized must be a non-empty string.")

    segments_raw = response.get("segments")
    if not isinstance(segments_raw, list):
        raise ValueError("Stage 1 response.segments must be an array.")
    segments = tuple(_validate_segment(item, index) for index, item in enumerate(segments_raw))
    reconstructed_raw = "".join(str(segment["raw"]) for segment in segments)
    reconstructed_reading = "".join(str(segment["reading"]) for segment in segments)

    fidelity_errors: list[str] = []
    if _without_whitespace(reconstructed_raw) != _without_whitespace(raw_text):
        fidelity_errors.append("segments.raw did not cover original_raw exactly once and in order")
    if _without_whitespace(reconstructed_reading) != _without_whitespace(normalized):
        fidelity_errors.append("normalized contained text not represented by segments.reading")
    new_kanji = _introduced_characters(normalized, raw_text, _is_kanji)
    if new_kanji:
        fidelity_errors.append(
            f"normalized introduced kanji absent from original_raw: {''.join(new_kanji)}"
        )
    new_punctuation = _introduced_characters(normalized, raw_text, _is_punctuation)
    if new_punctuation:
        fidelity_errors.append(
            "normalized introduced punctuation absent from original_raw: "
            f"{''.join(new_punctuation)}"
        )
    fidelity_errors.extend(_segment_fidelity_errors(segments, raw_text))

    uncertain_raw = response.get("uncertain")
    if not isinstance(uncertain_raw, list):
        raise ValueError("Stage 1 response.uncertain must be an array.")
    uncertain = tuple(
        _validate_uncertainty(item, index) for index, item in enumerate(uncertain_raw)
    )
    for index, item in enumerate(uncertain):
        if str(item["raw"]) not in raw_text:
            fidelity_errors.append(f"uncertainty {index}.raw was not present in original_raw")
    if fidelity_errors:
        raise ValueError("Stage 1 fidelity violation: " + "; ".join(fidelity_errors) + ".")
    return ReadingNormalizationResult(normalized, segments, uncertain)


def _validate_segment(value: Any, index: int) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"Stage 1 segment {index} must be an object.")
    raw = _required_string(value, "raw", f"segment {index}")
    reading = _required_string(value, "reading", f"segment {index}")
    if not raw:
        raise ValueError(f"Stage 1 segment {index}.raw must not be empty.")
    if not reading and not raw.isspace():
        raise ValueError(f"Stage 1 segment {index}.reading may be empty only for whitespace.")
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


def _prepare_local_ai_input(raw_text: str) -> PreparedLocalAIInput:
    masked = mask_protected_input(raw_text)
    return PreparedLocalAIInput(
        masked=masked,
        boundary_segments=tuple(_boundary_segments(masked.text)),
    )


def _input_payload(prepared: PreparedLocalAIInput) -> str:
    raw_text = prepared.masked.text
    return json.dumps(
        {
            "task": "reading_normalization_only",
            "original_raw": raw_text,
            "original_raw_masked": raw_text,
            "protected_placeholders": _protected_placeholders(prepared.masked.masks),
            "boundary_rule": (
                "Treat `|` as the Uttate rough-input separator inserted by Space. "
                "Do not merge, reorder, or infer across boundaries unless the raw text requires it."
            ),
            "preprocessed_segments": prepared.boundary_segments,
            "contract": {
                "preserve_meaning": True,
                "preserve_order": True,
                "do_not_add_or_complete": True,
                "do_not_translate_english": True,
                "cover_each_non_whitespace_character_once": True,
                "when_uncertain": "keep the raw span and report it in uncertain",
                "preserve_placeholders": True,
                "use_mechanical_reading_patterns_as_hints": True,
            },
            "required_exact_mappings": _required_exact_mappings(raw_text),
            "ascii_classification_hints": _ascii_classification_hints(raw_text),
        },
        ensure_ascii=False,
    )


def _repair_payload(prepared: PreparedLocalAIInput, validation_error: str) -> str:
    raw_text = prepared.masked.text
    return json.dumps(
        {
            "task": "repair_invalid_reading_normalization",
            "original_raw": raw_text,
            "original_raw_masked": raw_text,
            "protected_placeholders": _protected_placeholders(prepared.masked.masks),
            "preprocessed_segments": prepared.boundary_segments,
            "validation_error": validation_error,
            "required_exact_mappings": _required_exact_mappings(raw_text),
            "ascii_classification_hints": _ascii_classification_hints(raw_text),
            "instruction": (
                "Regenerate from original_raw. Do not defend or explain the previous output. "
                "Return only a schema-compliant object that satisfies the fidelity contract. "
                "Protected placeholders must be copied exactly and not interpreted."
            ),
        },
        ensure_ascii=False,
    )


def _protected_placeholders(masks: tuple[ProtectedMask, ...]) -> list[JsonObject]:
    return [
        {
            "placeholder": mask.placeholder,
            "kind": mask.kind.value,
            "instruction": "Copy this placeholder exactly. It will be restored after validation.",
        }
        for mask in masks
    ]


def _boundary_segments(raw_text: str) -> list[JsonObject]:
    segments: list[JsonObject] = []
    current: list[str] = []
    for character in raw_text:
        if character == "|":
            if current:
                segments.append(_mechanical_segment("".join(current)))
                current = []
            segments.append(
                {
                    "raw_masked": character,
                    "mechanical_strict": character,
                    "mechanical_typo_tolerant": character,
                    "kind": "boundary",
                    "suspicious_tokens": [],
                }
            )
            continue
        current.append(character)
    if current:
        segments.append(_mechanical_segment("".join(current)))
    return segments


def _mechanical_segment(text: str) -> JsonObject:
    suspicious_tokens: list[JsonObject] = []
    return {
        "raw_masked": text,
        "mechanical_strict": _mechanical_reading(text, typo_tolerant=False, suspicious=None),
        "mechanical_typo_tolerant": _mechanical_reading(
            text,
            typo_tolerant=True,
            suspicious=suspicious_tokens,
        ),
        "kind": "text",
        "suspicious_tokens": suspicious_tokens,
    }


def _mechanical_reading(
    text: str,
    *,
    typo_tolerant: bool,
    suspicious: list[JsonObject] | None,
) -> str:
    output: list[str] = []
    last_index = 0
    for match in _ROMAJI_TOKEN_PATTERN.finditer(text):
        output.append(text[last_index : match.start()])
        token = match.group(0)
        output.append(_mechanical_token_reading(token, typo_tolerant, suspicious))
        last_index = match.end()
    output.append(text[last_index:])
    return "".join(output)


def _mechanical_token_reading(
    token: str,
    typo_tolerant: bool,
    suspicious: list[JsonObject] | None,
) -> str:
    particle = _PARTICLE_READINGS.get(token.casefold())
    if particle is not None:
        return particle
    strict = _romaji_to_hiragana(token)
    if strict is not None and token.islower():
        return strict
    if not token.islower() or not typo_tolerant:
        if suspicious is not None and _is_suspicious_japanese_token(token):
            suspicious.append(
                {
                    "raw": token,
                    "reason": "not fully parseable as Japanese romaji; may be typo or non-Japanese",
                }
            )
        return token
    tolerant, changed = _romaji_to_hiragana_tolerant(token)
    if suspicious is not None and _is_suspicious_japanese_token(token):
        suspicious.append(
            {
                "raw": token,
                "reason": (
                    "contains consonant/vowel pattern that is not valid Japanese romaji "
                    "except yoon, n, or small-tsu"
                ),
            }
        )
    return tolerant if changed else token


def _romaji_to_hiragana_tolerant(token: str) -> tuple[str, bool]:
    value = token.casefold()
    index = 0
    reading: list[str] = []
    changed = False
    while index < len(value):
        if (
            index + 1 < len(value)
            and value[index] == value[index + 1]
            and value[index] not in "aeioun"
        ):
            reading.append("っ")
            index += 1
            changed = True
            continue
        if value[index] == "n" and (index + 1 == len(value) or value[index + 1] not in "aeiouy"):
            reading.append("ん")
            index += 1
            changed = True
            continue
        syllable = next(
            (item for item in _ROMAJI_SYLLABLES if value.startswith(item, index)),
            None,
        )
        if syllable is None:
            reading.append(token[index])
            index += 1
            continue
        reading.append(_ROMAJI_TO_HIRAGANA[syllable])
        index += len(syllable)
        changed = True
    return "".join(reading), changed


def _is_suspicious_japanese_token(token: str) -> bool:
    if not token.isascii() or not token.isalpha() or not token.islower():
        return False
    if not any(character in "aeiou" for character in token):
        return True
    if token[-1] not in "aeioun":
        return True
    return _romaji_to_hiragana(token) is None and _has_japanese_like_vowel_pattern(token)


def _has_japanese_like_vowel_pattern(token: str) -> bool:
    vowels = set("aeiou")
    consonant_run = 0
    for index, character in enumerate(token):
        if character in vowels:
            consonant_run = 0
            continue
        if character == "n":
            consonant_run = 0
            continue
        consonant_run += 1
        if consonant_run >= 2:
            pair = token[index - 1 : index + 1]
            if pair not in {"ky", "sh", "ch", "ny", "hy", "my", "ry", "gy", "by", "py", "ts"}:
                return True
    return False


def _restore_masked_result(
    result: ReadingNormalizationResult,
    masked: MaskedProtectedInput,
) -> ReadingNormalizationResult:
    return ReadingNormalizationResult(
        normalized=masked.restore(result.normalized),
        segments=tuple(_restore_masked_object(segment, masked) for segment in result.segments),
        uncertain=tuple(_restore_masked_object(item, masked) for item in result.uncertain),
    )


def _restore_masked_object(value: JsonObject, masked: MaskedProtectedInput) -> JsonObject:
    restored: JsonObject = {}
    for key, item in value.items():
        restored[key] = masked.restore(item) if isinstance(item, str) else item
    return restored


def _without_whitespace(value: str) -> str:
    return "".join(character for character in value if not character.isspace())


def _required_exact_mappings(raw_text: str) -> list[JsonObject]:
    mappings: list[JsonObject] = []
    for match in _ROMAJI_TOKEN_PATTERN.finditer(raw_text):
        raw = match.group(0)
        particle_reading = _PARTICLE_READINGS.get(raw.casefold())
        reading = particle_reading or (_romaji_to_hiragana(raw) if raw.islower() else None)
        if reading is not None:
            mappings.append(
                {
                    "raw": raw,
                    "required_reading": reading,
                    "type": "particle" if particle_reading is not None else "kana",
                }
            )
    return mappings


def _ascii_classification_hints(raw_text: str) -> JsonObject:
    likely_japanese: list[str] = []
    likely_english: list[str] = []
    name_or_acronym: list[str] = []
    for match in _ROMAJI_TOKEN_PATTERN.finditer(raw_text):
        token = match.group(0)
        if not token.islower():
            name_or_acronym.append(token)
        elif _looks_like_japanese_romaji(token):
            likely_japanese.append(token)
        else:
            likely_english.append(token)
    return {
        "likely_japanese_romaji": likely_japanese,
        "likely_english": likely_english,
        "name_or_acronym": name_or_acronym,
    }


def _looks_like_japanese_romaji(token: str) -> bool:
    return _romaji_to_hiragana(token) is not None


def _romaji_to_hiragana(token: str) -> str | None:
    value = token.casefold()
    index = 0
    reading: list[str] = []
    while index < len(value):
        if (
            index + 1 < len(value)
            and value[index] == value[index + 1]
            and value[index] not in "aeioun"
        ):
            reading.append("っ")
            index += 1
            continue
        if value[index] == "n" and (index + 1 == len(value) or value[index + 1] not in "aeiouy"):
            reading.append("ん")
            index += 1
            continue
        syllable = next(
            (item for item in _ROMAJI_SYLLABLES if value.startswith(item, index)),
            None,
        )
        if syllable is None:
            return None
        reading.append(_ROMAJI_TO_HIRAGANA[syllable])
        index += len(syllable)
    return "".join(reading) if value else None


def _apply_required_readings(response: JsonObject, raw_text: str) -> JsonObject:
    mappings = {str(item["raw"]): item for item in _required_exact_mappings(raw_text)}
    segments = response.get("segments")
    if not isinstance(segments, list):
        return response

    corrected = deepcopy(response)
    corrected_segments = corrected.get("segments")
    if not isinstance(corrected_segments, list):
        return response
    changed = False
    uncertain_value = corrected.get("uncertain")
    uncertain = uncertain_value if isinstance(uncertain_value, list) else None
    for segment in corrected_segments:
        if not isinstance(segment, dict):
            continue
        raw = segment.get("raw")
        mapping = mappings.get(raw) if isinstance(raw, str) else None
        if mapping is None:
            continue
        required_reading = mapping["required_reading"]
        required_type = mapping["type"]
        if segment.get("reading") != required_reading or segment.get("type") != required_type:
            segment["reading"] = required_reading
            segment["type"] = required_type
            changed = True
    for segment in corrected_segments:
        if not isinstance(segment, dict):
            continue
        raw = segment.get("raw")
        reading = segment.get("reading")
        if (
            isinstance(raw, str)
            and isinstance(reading, str)
            and raw == reading
            and raw.isascii()
            and raw.isalpha()
            and len(raw) >= 16
        ):
            segment["confidence"] = min(float(segment.get("confidence", 0.0)), 0.35)
            if uncertain is not None and not any(
                isinstance(item, dict) and item.get("raw") == raw for item in uncertain
            ):
                uncertain.append(
                    {
                        "raw": raw,
                        "reason": (
                            "長いASCII列に日本語ローマ字と英語が連結している可能性があるため、"
                            "原文を保持しました"
                        ),
                    }
                )
    if changed:
        corrected["normalized"] = " ".join(
            str(segment.get("reading", ""))
            for segment in corrected_segments
            if isinstance(segment, dict) and str(segment.get("reading", "")).strip()
        )
    return corrected


def _segment_fidelity_errors(segments: tuple[JsonObject, ...], raw_text: str) -> list[str]:
    errors: list[str] = []
    required_mappings = {
        str(item["raw"]): str(item["required_reading"])
        for item in _required_exact_mappings(raw_text)
    }
    for index, segment in enumerate(segments):
        raw = str(segment["raw"])
        reading = str(segment["reading"])
        segment_type = str(segment["type"])
        compact_raw = _without_whitespace(raw)
        compact_reading = _without_whitespace(reading)
        expected_particle = _PARTICLE_READINGS.get(compact_raw.casefold())
        if (
            expected_particle is not None
            and segment_type in {"particle", "kana"}
            and compact_reading != expected_particle
        ):
            errors.append(
                f"segment {index} changed particle {raw!r}; expected {expected_particle!r}"
            )
        expected_reading = required_mappings.get(raw)
        if expected_reading is not None and compact_reading != expected_reading:
            errors.append(
                f"segment {index} did not use required reading {expected_reading!r} for {raw!r}"
            )
        if segment_type == "english" and compact_reading != compact_raw:
            errors.append(f"segment {index} translated or changed English text {raw!r}")
        if (
            compact_raw.islower()
            and _looks_like_japanese_romaji(compact_raw)
            and compact_raw.casefold() not in _PARTICLE_READINGS
            and compact_reading.casefold() == compact_raw.casefold()
        ):
            errors.append(f"segment {index} left likely Japanese romaji unnormalized: {raw!r}")
        if segment_type == "unknown" and compact_reading != compact_raw:
            errors.append(f"segment {index} changed unknown text {raw!r}")
    return errors


def _introduced_characters(output: str, source: str, predicate: Any) -> list[str]:
    source_counts = Counter(character for character in source if predicate(character))
    introduced: list[str] = []
    for character in output:
        if not predicate(character):
            continue
        if source_counts[character] > 0:
            source_counts[character] -= 1
        elif character not in introduced:
            introduced.append(character)
    return introduced


def _is_kanji(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def _is_punctuation(character: str) -> bool:
    return unicodedata.category(character).startswith("P")
