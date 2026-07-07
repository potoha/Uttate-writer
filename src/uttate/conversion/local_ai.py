from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from importlib import resources
from typing import Protocol

from uttate.conversion.direct import restore_masked_provider_result
from uttate.conversion.response_parser import parse_provider_result
from uttate.input_rules import (
    ROMAJI_TABLE,
    MaskedProtectedInput,
    ProtectedMask,
    mask_protected_input,
)
from uttate.models import JsonObject
from uttate.providers.base import Candidate, ProviderError, ProviderResult

LOGGER = logging.getLogger(__name__)

AMBIGUITY_RESOLUTION_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "number"},
                    "reading": {"type": "string"},
                    "type": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["id", "reading", "type", "confidence"],
                "additionalProperties": False,
            },
        },
        "uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["choices", "uncertain"],
    "additionalProperties": False,
}

LOCAL_AI_STAGE2_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["label", "text"],
                "additionalProperties": False,
            },
        },
        "uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["text", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["candidates", "uncertain"],
    "additionalProperties": False,
}

_PROTECTED_PLACEHOLDER_PATTERN = re.compile(r"__UTTATE_PROTECTED_\d+__")
_SEGMENT_PATTERN = re.compile(r"__UTTATE_PROTECTED_\d+__|\s*\|\s*|[^\s|]+|\s+")
_ASCII_WORD_PATTERN = re.compile(r"[A-Za-z]+(?:[+＋][A-Za-z]+)*")
_ROMAJI_KEYS = tuple(sorted(ROMAJI_TABLE, key=len, reverse=True))
_N_SEPARATOR_CHARS = "+＋"

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
_AMBIGUOUS_PARTICLES = {"to"}
_MIXED_PARTICLES = {"ha", "wo", "e", "de", "no", "ni", "to", "ga", "mo"}
_KNOWN_ENGLISH_TERMS = {
    "api",
    "gemini",
    "github",
    "ime",
    "input",
    "keyboard",
    "llm",
    "openai",
    "replacement",
    "stress",
    "test",
    "tool",
    "uttate",
}
_ENGLISH_TERMS_BY_LENGTH = tuple(sorted(_KNOWN_ENGLISH_TERMS, key=len, reverse=True))


@dataclass(frozen=True, slots=True)
class TokenReading:
    reading: str
    token_type: str
    confidence: float
    candidates: tuple[JsonObject, ...] = ()
    suspicious_candidates: tuple[JsonObject, ...] = ()
    suspicious_reason: str = ""


@dataclass(frozen=True, slots=True)
class MechanicalReadingResult:
    original_raw: str
    mechanical_normalized: str
    segments: tuple[JsonObject, ...]
    ambiguous_spans: tuple[JsonObject, ...]
    suspicious_spans: tuple[JsonObject, ...]
    resolved_normalized: str | None = None

    @property
    def normalized_for_stage2(self) -> str:
        return self.resolved_normalized or self.mechanical_normalized


@dataclass(frozen=True, slots=True)
class ReadingNormalizationResult:
    normalized: str
    segments: tuple[JsonObject, ...]
    uncertain: tuple[JsonObject, ...]


@dataclass(frozen=True, slots=True)
class PreparedLocalAIInput:
    masked: MaskedProtectedInput
    segment_plan: tuple[JsonObject, ...]

    @property
    def boundary_segments(self) -> tuple[JsonObject, ...]:
        """Backward-compatible alias for older tests and docs."""

        return self.segment_plan


class LocalAILLMProvider(Protocol):
    """Structured JSON boundary used by the local AI stages."""

    def complete_json(
        self,
        messages: list[JsonObject],
        schema: JsonObject | None = None,
    ) -> JsonObject:
        """Complete a chat request and return one decoded JSON object."""
        ...


class MechanicalReadingNormalizer:
    """Deterministic Stage 1 reading normalizer for masked rough input."""

    def normalize(self, original_raw_masked: str) -> MechanicalReadingResult:
        if not original_raw_masked:
            return MechanicalReadingResult("", "", (), (), ())

        segments: list[JsonObject] = []
        ambiguous_spans: list[JsonObject] = []
        suspicious_spans: list[JsonObject] = []
        for segment_id, raw in enumerate(_split_segment_plan(original_raw_masked)):
            segment = self._normalize_segment(segment_id, raw)
            segments.append(segment)
            if segment.get("candidates"):
                ambiguous_spans.append(
                    {
                        "id": segment_id,
                        "raw": raw,
                        "current_reading": segment["reading"],
                        "candidates": segment["candidates"],
                    }
                )
            if segment.get("suspicious_candidates") or segment.get("suspicious_reason"):
                suspicious_spans.append(
                    {
                        "id": segment_id,
                        "raw": raw,
                        "current_reading": segment["reading"],
                        "candidates": segment.get("suspicious_candidates", []),
                        "reason": segment.get("suspicious_reason", "suspicious reading"),
                    }
                )

        mechanical_normalized = "".join(str(segment["reading"]) for segment in segments)
        _validate_mechanical_result(original_raw_masked, mechanical_normalized, segments)
        return MechanicalReadingResult(
            original_raw=original_raw_masked,
            mechanical_normalized=mechanical_normalized,
            segments=tuple(segments),
            ambiguous_spans=tuple(ambiguous_spans),
            suspicious_spans=tuple(suspicious_spans),
        )

    def _normalize_segment(self, segment_id: int, raw: str) -> JsonObject:
        if _PROTECTED_PLACEHOLDER_PATTERN.fullmatch(raw):
            return _segment(segment_id, raw, raw, "protected", "protected", 1.0)
        if "|" in raw and raw.strip() == "|":
            return _segment(segment_id, raw, raw, "boundary", "boundary", 1.0)
        if raw.isspace() or _is_symbol_only(raw):
            return _segment(segment_id, raw, raw, "symbol", "symbol", 1.0)

        reading, token_type, confidence, candidates, suspicious_candidates, reason = (
            _normalize_text_segment(raw)
        )
        kind = "unknown" if token_type == "unknown" else "text"
        return _segment(
            segment_id,
            raw,
            reading,
            kind,
            token_type,
            confidence,
            candidates=candidates,
            suspicious_candidates=suspicious_candidates,
            suspicious_reason=reason,
        )


class AmbiguityResolver:
    """Optional Stage 1.5 chooser. It can only select from mechanical candidates."""

    def __init__(self, provider: LocalAILLMProvider, *, system_prompt: str) -> None:
        self.provider = provider
        self.system_prompt = system_prompt

    def resolve(self, result: MechanicalReadingResult) -> MechanicalReadingResult:
        if not result.ambiguous_spans:
            return result

        payload = {
            "task": "resolve_ambiguous_readings_only",
            "mechanical_normalized": result.mechanical_normalized,
            "ambiguous_spans": result.ambiguous_spans,
            "rules": {
                "choose_only_from_candidates": True,
                "do_not_rewrite_full_text": True,
                "do_not_add_text": True,
                "preserve_placeholders": True,
            },
        }
        messages: list[JsonObject] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            response = self.provider.complete_json(messages, AMBIGUITY_RESOLUTION_SCHEMA)
        except Exception as error:
            LOGGER.debug("[local-ai] ambiguity resolver fallback used: %s", error)
            return result

        choices = _valid_ambiguity_choices(response, result.ambiguous_spans)
        if not choices:
            LOGGER.debug("[local-ai] ambiguity resolver produced no valid choices")
            return result

        segments = [dict(segment) for segment in result.segments]
        for segment_id, choice in choices.items():
            segment = segments[segment_id]
            if segment["kind"] in {"protected", "boundary"}:
                continue
            segment["reading"] = choice["reading"]
            segment["type"] = choice["type"]
            segment["confidence"] = choice["confidence"]
        resolved = "".join(str(segment["reading"]) for segment in segments)
        try:
            _validate_mechanical_result(result.original_raw, resolved, segments)
        except ValueError:
            return result
        return replace(result, segments=tuple(segments), resolved_normalized=resolved)


class Stage2Converter:
    """Local AI Stage 2: normalized kana/English input to kanji-kana candidates."""

    def __init__(self, provider: LocalAILLMProvider, *, system_prompt: str) -> None:
        self.provider = provider
        self.system_prompt = system_prompt

    def convert(
        self,
        result: MechanicalReadingResult,
        *,
        masked: MaskedProtectedInput,
        previous_context: str,
        candidate_count: int,
        model: str = "",
    ) -> ProviderResult:
        normalized = result.normalized_for_stage2
        payload = {
            "task": "aggressive_kanji_conversion_from_normalized_reading",
            "conversion_stage": "stage2_kanji_conversion",
            "input_text": normalized,
            "normalized_input": normalized,
            "previous_context": previous_context.strip() or "(なし)",
            "candidate_count": candidate_count,
            "labels": ["faithful", "natural"],
            "protected_placeholders": _protected_placeholders(masked.masks),
            "kanji_conversion_policy": {
                "convert_common_nouns": True,
                "convert_verb_stems": True,
                "convert_adjective_stems": True,
                "convert_sahen_nouns": True,
                "convert_compound_words": True,
                "convert_technical_terms": True,
                "preserve_particles_in_hiragana": True,
                "preserve_auxiliaries_in_hiragana": True,
                "preserve_okurigana": True,
                "preserve_english": True,
                "preserve_placeholders": True,
                "avoid_unnecessary_hiragana": True,
                "do_not_add_meaning": True,
                "keep_casual_style": True,
            },
            "rules": {
                "preserve_placeholders": True,
                "do_not_translate_english_terms": True,
                "do_not_add_meaning": True,
                "return_faithful_and_natural": True,
                "convert_kana_to_common_kanji_when_clear": True,
                "rough_separator_pipe_is_not_literal_output": True,
            },
        }
        messages: list[JsonObject] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        LOGGER.debug("[local-ai] stage2 request input: %s", normalized)
        response = self.provider.complete_json(messages, LOCAL_AI_STAGE2_SCHEMA)
        raw_response = json.dumps(response, ensure_ascii=False)
        LOGGER.debug("[local-ai] stage2 raw response: %s", raw_response)
        provider_result = parse_provider_result(
            raw_response,
            provider="local_ai",
            model=model,
            candidate_count=candidate_count,
            raw_response=raw_response,
        )
        provider_result = _stage2_result_with_valid_placeholders(provider_result, normalized)
        LOGGER.debug(
            "[local-ai] stage2 parsed candidates count: %s",
            len(provider_result.candidates),
        )
        return restore_masked_provider_result(provider_result, masked)


class ReadingNormalizer:
    def __init__(
        self,
        provider: LocalAILLMProvider,
        *,
        system_prompt: str | None = None,
        stage2_system_prompt: str | None = None,
        enable_ambiguity_resolver: bool = True,
        enable_stage2: bool = True,
        max_validation_attempts: int = 2,
    ) -> None:
        if max_validation_attempts <= 0:
            raise ValueError("max_validation_attempts must be positive.")
        self.provider = provider
        self.system_prompt = system_prompt or load_default_system_prompt()
        self.stage2_system_prompt = stage2_system_prompt or load_stage2_system_prompt()
        self.enable_ambiguity_resolver = enable_ambiguity_resolver
        self.enable_stage2 = enable_stage2
        self.max_validation_attempts = max_validation_attempts
        self.mechanical_normalizer = MechanicalReadingNormalizer()

    def normalize(self, raw_text: str) -> ReadingNormalizationResult:
        prepared, result = self._normalize_masked(raw_text)
        restored_segments = tuple(
            _restore_masked_object(segment, prepared.masked) for segment in result.segments
        )
        return ReadingNormalizationResult(
            normalized=prepared.masked.restore(result.normalized_for_stage2),
            segments=restored_segments,
            uncertain=_restored_uncertain(result, prepared.masked),
        )

    def convert_to_provider_result(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
        model: str = "",
    ) -> ProviderResult:
        prepared, result = self._normalize_masked(raw_text)
        if self.enable_stage2:
            try:
                provider_result = Stage2Converter(
                    self.provider,
                    system_prompt=self.stage2_system_prompt,
                ).convert(
                    result,
                    masked=prepared.masked,
                    previous_context=previous_context,
                    candidate_count=candidate_count,
                    model=model,
                )
                LOGGER.debug("[local-ai] stage2 fallback used: false")
                return provider_result
            except Exception as error:
                LOGGER.debug("[local-ai] stage2 fallback used: true reason=%s", error)

        return self._fallback_provider_result(result, prepared.masked, model=model)

    def _normalize_masked(
        self,
        raw_text: str,
    ) -> tuple[PreparedLocalAIInput, MechanicalReadingResult]:
        if not raw_text.strip():
            raise ValueError("raw_text must not be empty.")
        prepared = _prepare_local_ai_input(raw_text)
        result = self.mechanical_normalizer.normalize(prepared.masked.text)
        LOGGER.debug(
            "[local-ai] stage1 mechanical normalized: %s",
            result.mechanical_normalized,
        )
        LOGGER.debug("[local-ai] stage1 ambiguous count: %s", len(result.ambiguous_spans))
        if self.enable_ambiguity_resolver and result.ambiguous_spans:
            result = AmbiguityResolver(
                self.provider,
                system_prompt=self.system_prompt,
            ).resolve(result)
        return prepared, result

    def _fallback_provider_result(
        self,
        result: MechanicalReadingResult,
        masked: MaskedProtectedInput,
        *,
        model: str,
    ) -> ProviderResult:
        return ProviderResult(
            candidates=(
                Candidate(
                    "mechanical_normalized",
                    masked.restore(result.normalized_for_stage2),
                ),
            ),
            uncertain=_restored_uncertain(result, masked),
            provider="local_ai",
            model=model,
        )


class ReadingNormalizationProvider:
    """Adapt the local staged conversion flow to the UI queue."""

    def __init__(self, normalizer: ReadingNormalizer) -> None:
        self.normalizer = normalizer

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        if candidate_count <= 0:
            raise ValueError("candidate_count must be positive.")
        return self.normalizer.convert_to_provider_result(
            raw_text,
            previous_context=previous_context,
            candidate_count=candidate_count,
        )


def load_default_system_prompt() -> str:
    return (
        resources.files("uttate.prompts")
        .joinpath("reading_normalizer.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def load_stage2_system_prompt() -> str:
    return (
        resources.files("uttate.prompts")
        .joinpath("local_ai_stage2_converter.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def _prepare_local_ai_input(raw_text: str) -> PreparedLocalAIInput:
    masked = mask_protected_input(raw_text)
    return PreparedLocalAIInput(masked=masked, segment_plan=tuple(_segment_plan(masked.text)))


def _input_payload(prepared: PreparedLocalAIInput) -> str:
    mechanical = MechanicalReadingNormalizer().normalize(prepared.masked.text)
    return json.dumps(
        {
            "task": "resolve_ambiguous_readings_only",
            "original_raw": prepared.masked.text,
            "original_raw_masked": prepared.masked.text,
            "mechanical_normalized": mechanical.mechanical_normalized,
            "protected_placeholders": _protected_placeholders(prepared.masked.masks),
            "segment_plan": list(prepared.segment_plan),
            "segments": list(mechanical.segments),
            "ambiguous_spans": list(mechanical.ambiguous_spans),
            "suspicious_spans": list(mechanical.suspicious_spans),
            "rules": {
                "choose_only_from_candidates": True,
                "do_not_rewrite_full_text": True,
                "do_not_add_text": True,
                "preserve_placeholders": True,
            },
        },
        ensure_ascii=False,
    )


def _segment_plan(raw_text: str) -> list[JsonObject]:
    return [
        {
            "id": index,
            "raw": raw,
            "kind": _segment_kind(raw),
        }
        for index, raw in enumerate(_split_segment_plan(raw_text))
    ]


def _split_segment_plan(raw_text: str) -> list[str]:
    return [match.group(0) for match in _SEGMENT_PATTERN.finditer(raw_text)]


def _segment_kind(raw: str) -> str:
    if _PROTECTED_PLACEHOLDER_PATTERN.fullmatch(raw):
        return "protected"
    if "|" in raw and raw.strip() == "|":
        return "boundary"
    if raw.isspace() or _is_symbol_only(raw):
        return "symbol"
    return "text"


def _segment(
    segment_id: int,
    raw: str,
    reading: str,
    kind: str,
    token_type: str,
    confidence: float,
    *,
    candidates: tuple[JsonObject, ...] = (),
    suspicious_candidates: tuple[JsonObject, ...] = (),
    suspicious_reason: str = "",
) -> JsonObject:
    return {
        "id": segment_id,
        "raw": raw,
        "reading": reading,
        "kind": kind,
        "type": token_type,
        "confidence": confidence,
        "candidates": list(candidates),
        "suspicious_candidates": list(suspicious_candidates),
        "suspicious_reason": suspicious_reason,
    }


def _normalize_text_segment(
    raw: str,
) -> tuple[str, str, float, tuple[JsonObject, ...], tuple[JsonObject, ...], str]:
    output: list[str] = []
    token_types: list[str] = []
    confidences: list[float] = []
    candidates: list[JsonObject] = []
    suspicious_candidates: list[JsonObject] = []
    suspicious_reasons: list[str] = []
    last_index = 0

    for match in _ASCII_WORD_PATTERN.finditer(raw):
        output.append(raw[last_index : match.start()])
        token = match.group(0)
        token_reading = _normalize_ascii_token(token)
        output.append(token_reading.reading)
        token_types.append(token_reading.token_type)
        confidences.append(token_reading.confidence)
        candidates.extend(token_reading.candidates)
        suspicious_candidates.extend(token_reading.suspicious_candidates)
        if token_reading.suspicious_reason:
            suspicious_reasons.append(token_reading.suspicious_reason)
        last_index = match.end()

    output.append(raw[last_index:])
    if not token_types:
        return raw, "symbol" if _is_symbol_only(raw) else "unknown", 1.0, (), (), ""
    return (
        "".join(output),
        _combined_type(token_types),
        min(confidences),
        tuple(candidates),
        tuple(suspicious_candidates),
        "; ".join(suspicious_reasons),
    )


def _normalize_ascii_token(token: str) -> TokenReading:
    lowered = token.casefold()

    if lowered in _KNOWN_ENGLISH_TERMS:
        return TokenReading(token, "english", 0.95)
    if lowered in _PARTICLE_READINGS:
        reading = _PARTICLE_READINGS[lowered]
        candidates: tuple[JsonObject, ...] = ()
        confidence = 0.9
        if lowered in _AMBIGUOUS_PARTICLES:
            candidates = (
                {
                    "reading": reading,
                    "type": "japanese_particle",
                    "reason": "Japanese particle candidate",
                },
                {
                    "reading": token,
                    "type": "english",
                    "reason": "English word candidate",
                },
            )
            confidence = 0.72
        return TokenReading(reading, "japanese_particle", confidence, candidates=candidates)

    strict = _strict_romaji_to_hiragana(lowered) if token.islower() else None
    if strict is not None:
        n_y_candidates = _n_y_ambiguity_candidates(lowered, strict)
        if n_y_candidates:
            return TokenReading(
                strict,
                "japanese_romaji",
                0.78,
                candidates=(
                    {
                        "reading": strict,
                        "type": "japanese_romaji",
                        "reason": "Unmarked n+y romaji candidate",
                    },
                    *(
                        {
                            "reading": candidate,
                            "type": "japanese_romaji_n_separator",
                            "reason": "Treat n before y as ん boundary",
                        }
                        for candidate in n_y_candidates
                    ),
                ),
            )
        return TokenReading(strict, "japanese_romaji", 0.95)

    mixed = _split_mixed_ascii_token(token)
    if mixed is not None:
        reading = " ".join(part.reading for part in mixed)
        token_types = [part.token_type for part in mixed]
        candidates = tuple(candidate for part in mixed for candidate in part.candidates)
        suspicious_candidates = tuple(
            candidate for part in mixed for candidate in part.suspicious_candidates
        )
        suspicious_reasons = [
            part.suspicious_reason for part in mixed if part.suspicious_reason
        ]
        return TokenReading(
            reading,
            _combined_type(token_types),
            min(part.confidence for part in mixed),
            candidates=candidates,
            suspicious_candidates=suspicious_candidates,
            suspicious_reason="; ".join(suspicious_reasons),
        )

    if not token.islower():
        return TokenReading(token, "name_like", 0.95)

    typo_candidates = _typo_tolerant_candidates(lowered)
    if typo_candidates:
        return TokenReading(
            token,
            "unknown",
            0.42,
            suspicious_candidates=tuple(
                {
                    "reading": candidate,
                    "type": "japanese_romaji_typo_tolerant",
                    "reason": "Minor romaji typo candidate",
                }
                for candidate in typo_candidates
            ),
            suspicious_reason="not fully parseable as Japanese romaji",
        )
    if _looks_english_like(token):
        return TokenReading(token, "english", 0.85)
    return TokenReading(
        token,
        "unknown",
        0.35,
        suspicious_reason="not parseable as Japanese romaji or a known English token",
    )


def _split_mixed_ascii_token(token: str) -> tuple[TokenReading, ...] | None:
    lowered = token.casefold()
    if not any(term in lowered for term in _KNOWN_ENGLISH_TERMS):
        return None

    parts: list[TokenReading] = []
    index = 0
    while index < len(token):
        english = _matching_english_term(lowered, index)
        if english:
            raw = token[index : index + len(english)]
            parts.append(TokenReading(raw, "english", 0.95))
            index += len(english)
            continue

        particle = _matching_particle(lowered, index)
        if particle:
            parts.append(TokenReading(_PARTICLE_READINGS[particle], "japanese_particle", 0.88))
            index += len(particle)
            continue

        next_english = _next_english_index(lowered, index)
        end = next_english if next_english is not None else len(token)
        raw = token[index:end]
        parts.append(_normalize_non_mixed_tail(raw))
        index = end

    if len(parts) <= 1 or any(part.token_type == "unknown" for part in parts):
        return None
    return tuple(parts)


def _normalize_non_mixed_tail(raw: str) -> TokenReading:
    if not raw:
        return TokenReading(raw, "symbol", 1.0)
    lowered = raw.casefold()
    particle = _PARTICLE_READINGS.get(lowered)
    if particle is not None:
        return TokenReading(particle, "japanese_particle", 0.88)
    strict = _strict_romaji_to_hiragana(lowered) if raw.islower() else None
    if strict is not None:
        return TokenReading(strict, "japanese_romaji", 0.9)
    return _normalize_ascii_token(raw)


def _matching_english_term(lowered: str, index: int) -> str | None:
    return next(
        (term for term in _ENGLISH_TERMS_BY_LENGTH if lowered.startswith(term, index)),
        None,
    )


def _matching_particle(lowered: str, index: int) -> str | None:
    particles = sorted(_MIXED_PARTICLES, key=len, reverse=True)
    return next(
        (particle for particle in particles if lowered.startswith(particle, index)),
        None,
    )


def _next_english_index(lowered: str, index: int) -> int | None:
    positions = [lowered.find(term, index) for term in _KNOWN_ENGLISH_TERMS]
    positions = [position for position in positions if position >= 0]
    return min(positions) if positions else None


def _strict_romaji_to_hiragana(token: str) -> str | None:
    if not token:
        return None
    value = token.casefold()
    index = 0
    reading: list[str] = []
    while index < len(value):
        if _is_double_consonant(value, index):
            reading.append("っ")
            index += 1
            continue
        if value[index] == "n":
            next_char = value[index + 1] if index + 1 < len(value) else ""
            after_next = value[index + 2] if index + 2 < len(value) else ""
            if next_char in _N_SEPARATOR_CHARS and after_next.isalpha():
                reading.append("ん")
                index += 2
                continue
            if not next_char:
                reading.append("ん")
                index += 1
                continue
            if next_char == "n" and after_next not in "aiueoy":
                reading.append("ん")
                index += 2
                continue
            if next_char not in "aiueoy":
                reading.append("ん")
                index += 1
                continue
        syllable = next((key for key in _ROMAJI_KEYS if value.startswith(key, index)), None)
        if syllable is None:
            return None
        reading.append(ROMAJI_TABLE[syllable])
        index += len(syllable)
    return "".join(reading)


def _n_y_ambiguity_candidates(token: str, primary_reading: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for index in range(len(token) - 2):
        if token[index] != "n" or token[index + 1] != "y":
            continue
        if token[index + 2] not in "auo":
            continue
        marked = f"{token[: index + 1]}+{token[index + 1 :]}"
        reading = _strict_romaji_to_hiragana(marked)
        if reading is not None and reading != primary_reading:
            candidates.append(reading)
    return tuple(dict.fromkeys(candidates))


def _is_double_consonant(value: str, index: int) -> bool:
    if index + 1 >= len(value):
        return False
    char = value[index]
    return char == value[index + 1] and char not in "aeioun"


def _typo_tolerant_candidates(token: str) -> list[str]:
    candidates: list[str] = []
    if token and token[-1] not in "aeioun":
        reading = _strict_romaji_to_hiragana(token + "u")
        if reading is not None:
            candidates.append(reading)
    collapsed_n = re.sub(r"n{3,}", "nn", token)
    if collapsed_n != token:
        reading = _strict_romaji_to_hiragana(collapsed_n)
        if reading is not None:
            candidates.append(reading)
    return list(dict.fromkeys(candidates))


def _looks_english_like(token: str) -> bool:
    lowered = token.casefold()
    if len(lowered) <= 2:
        return False
    if any(cluster in lowered for cluster in ("str", "pl", "cl", "tr", "dr", "tion")):
        return True
    return lowered.endswith(("ing", "er", "ed", "ly", "ment"))


def _combined_type(token_types: list[str]) -> str:
    unique = set(token_types)
    if len(unique) == 1:
        return token_types[0]
    if unique <= {"japanese_romaji", "japanese_particle"}:
        return "japanese_romaji"
    if "unknown" in unique:
        return "unknown"
    return "mixed"


def _is_symbol_only(raw: str) -> bool:
    return bool(raw) and not any(character.isalnum() for character in raw)


def _validate_mechanical_result(
    original_raw: str,
    mechanical_normalized: str,
    segments: list[JsonObject] | tuple[JsonObject, ...],
) -> None:
    if "".join(str(segment["raw"]) for segment in segments) != original_raw:
        raise ValueError("segment raw coverage must exactly match original_raw.")
    if "".join(str(segment["reading"]) for segment in segments) != mechanical_normalized:
        raise ValueError("segment readings must exactly match mechanical_normalized.")
    segment_ids = {int(segment["id"]) for segment in segments}
    for segment in segments:
        confidence = segment["confidence"]
        if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
            raise ValueError("segment confidence must be between 0 and 1.")
        if segment["kind"] in {"protected", "boundary"} and segment["reading"] != segment["raw"]:
            raise ValueError("protected and boundary segments must be preserved.")
        if int(segment["id"]) not in segment_ids:
            raise ValueError("segment id was invalid.")


def _valid_ambiguity_choices(
    response: JsonObject,
    ambiguous_spans: tuple[JsonObject, ...],
) -> dict[int, JsonObject]:
    choices_raw = response.get("choices")
    if not isinstance(choices_raw, list):
        return {}
    spans = {int(span["id"]): span for span in ambiguous_spans}
    choices: dict[int, JsonObject] = {}
    for choice in choices_raw:
        if not isinstance(choice, dict):
            continue
        choice_id = choice.get("id")
        if isinstance(choice_id, bool) or not isinstance(choice_id, int | float):
            continue
        segment_id = int(choice_id)
        span = spans.get(segment_id)
        if span is None:
            continue
        reading = choice.get("reading")
        choice_type = choice.get("type")
        confidence = choice.get("confidence")
        if (
            not isinstance(reading, str)
            or not isinstance(choice_type, str)
            or isinstance(confidence, bool)
            or not isinstance(confidence, int | float)
            or not 0 <= confidence <= 1
        ):
            continue
        allowed = {
            str(candidate["reading"])
            for candidate in span.get("candidates", [])
            if isinstance(candidate, dict) and isinstance(candidate.get("reading"), str)
        }
        if reading not in allowed:
            continue
        choices[segment_id] = {
            "reading": reading,
            "type": choice_type,
            "confidence": float(confidence),
        }
    return choices


def _stage2_result_with_valid_placeholders(
    result: ProviderResult,
    normalized_input: str,
) -> ProviderResult:
    placeholders = set(_PROTECTED_PLACEHOLDER_PATTERN.findall(normalized_input))
    if not placeholders:
        return result

    valid_candidates: list[Candidate] = []
    for candidate in result.candidates:
        if all(
            candidate.text.count(placeholder) == normalized_input.count(placeholder)
            for placeholder in placeholders
        ):
            valid_candidates.append(candidate)
        else:
            LOGGER.debug(
                "[local-ai] stage2 candidate dropped because placeholder changed: %s",
                candidate.text,
            )
    if not valid_candidates:
        raise ProviderError("Stage 2 response changed or dropped protected placeholders.")
    if len(valid_candidates) == len(result.candidates):
        return result
    return ProviderResult(
        candidates=tuple(valid_candidates),
        uncertain=result.uncertain,
        provider=result.provider,
        model=result.model,
        raw_response=result.raw_response,
        usage=result.usage,
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


def _restore_masked_object(value: JsonObject, masked: MaskedProtectedInput) -> JsonObject:
    restored: JsonObject = {}
    for key, item in value.items():
        if key in {"candidates", "suspicious_candidates"} and isinstance(item, list):
            restored[key] = [
                _restore_masked_object(candidate, masked)
                if isinstance(candidate, dict)
                else masked.restore(candidate)
                if isinstance(candidate, str)
                else candidate
                for candidate in item
            ]
        else:
            restored[key] = masked.restore(item) if isinstance(item, str) else item
    return restored


def _restored_uncertain(
    result: MechanicalReadingResult,
    masked: MaskedProtectedInput,
) -> tuple[JsonObject, ...]:
    uncertain: list[JsonObject] = []
    for span in (*result.ambiguous_spans, *result.suspicious_spans):
        restored = _restore_masked_object(span, masked)
        uncertain.append(
            {
                "raw": str(restored.get("raw", "")),
                "reason": str(restored.get("reason", "ambiguous or suspicious reading")),
                "candidates": [
                    str(candidate.get("reading"))
                    for candidate in restored.get("candidates", [])
                    if isinstance(candidate, dict) and isinstance(candidate.get("reading"), str)
                ],
            }
        )
    return tuple(uncertain)
