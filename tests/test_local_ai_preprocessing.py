import json

from uttate.conversion.local_ai import (
    AmbiguityResolver,
    MechanicalReadingNormalizer,
    _input_payload,
    _prepare_local_ai_input,
)
from uttate.input_rules import mask_protected_input
from uttate.models import JsonObject


class ChoiceProvider:
    def __init__(self, response: JsonObject) -> None:
        self.response = response

    def complete_json(
        self,
        messages: list[JsonObject],
        schema: JsonObject | None = None,
    ) -> JsonObject:
        del messages, schema
        return self.response


def test_mechanical_normalizer_basic_romaji() -> None:
    result = MechanicalReadingNormalizer().normalize(
        "nihonngo | henkan | koreha | bennrina | dane."
    )

    assert result.mechanical_normalized == "にほんご | へんかん | これは | べんりな | だね."
    assert result.suspicious_spans == ()


def test_mechanical_normalizer_preserves_protected_placeholders() -> None:
    masked = mask_protected_input("nihonngo | =tool= | \\siromono\\ | $tokiori$")
    result = MechanicalReadingNormalizer().normalize(masked.text)

    assert "__UTTATE_PROTECTED_0__" in result.mechanical_normalized
    assert all(
        segment["reading"] == segment["raw"]
        for segment in result.segments
        if segment["kind"] == "protected"
    )
    assert masked.restore(result.mechanical_normalized) == (
        "にほんご | tool | シロモノ | ときおり"
    )


def test_segment_plan_covers_original_raw() -> None:
    prepared = _prepare_local_ai_input(
        "nihonngo | henkan | =tool= | koreha | bennrina | \\siromono\\ | dane."
    )

    assert "".join(item["raw"] for item in prepared.segment_plan) == prepared.masked.text


def test_mechanical_normalized_matches_segment_readings() -> None:
    result = MechanicalReadingNormalizer().normalize("nihonngo | henkan | koreha")

    assert "".join(segment["raw"] for segment in result.segments) == result.original_raw
    assert (
        "".join(segment["reading"] for segment in result.segments)
        == result.mechanical_normalized
    )


def test_boundary_is_preserved() -> None:
    result = MechanicalReadingNormalizer().normalize("koreha | test | dane")

    assert result.mechanical_normalized == "これは | test | だね"
    assert any(segment["raw"] == " | " for segment in result.segments)


def test_english_tokens_are_preserved() -> None:
    result = MechanicalReadingNormalizer().normalize(
        "keyboardha inputnostresswosaishoukashinakerebanaranai"
    )

    assert result.mechanical_normalized == (
        "keyboard は input の stress を さいしょうかしなければならない"
    )


def test_short_particles_are_handled() -> None:
    result = MechanicalReadingNormalizer().normalize("koreha input no test dane")

    assert result.mechanical_normalized == "これは input の test だね"


def test_n_plus_marks_moraic_n_before_y_sound() -> None:
    result = MechanicalReadingNormalizer().normalize("in+you")

    assert result.mechanical_normalized == "いんよう"
    assert result.ambiguous_spans == ()


def test_unmarked_n_y_keeps_primary_reading_and_records_boundary_candidate() -> None:
    result = MechanicalReadingNormalizer().normalize("inyou")

    assert result.mechanical_normalized == "いにょう"
    assert result.ambiguous_spans
    assert result.ambiguous_spans[0]["raw"] == "inyou"
    readings = {candidate["reading"] for candidate in result.ambiguous_spans[0]["candidates"]}
    assert readings == {"いにょう", "いんよう"}


def test_suspicious_token_is_recorded() -> None:
    result = MechanicalReadingNormalizer().normalize("nyuryok")

    assert result.suspicious_spans
    assert result.suspicious_spans[0]["raw"] == "nyuryok"
    assert result.suspicious_spans[0]["candidates"]


def test_ambiguity_resolver_chooses_only_from_candidates() -> None:
    mechanical = MechanicalReadingNormalizer().normalize("to")
    response = {
        "choices": [
            {
                "id": mechanical.ambiguous_spans[0]["id"],
                "reading": "to",
                "type": "english",
                "confidence": 0.82,
            }
        ],
        "uncertain": [],
    }

    resolved = AmbiguityResolver(
        ChoiceProvider(response),
        system_prompt="choose",
    ).resolve(mechanical)

    assert resolved.normalized_for_stage2 == "to"


def test_ambiguity_resolver_rejects_new_reading() -> None:
    mechanical = MechanicalReadingNormalizer().normalize("to")
    response = {
        "choices": [
            {
                "id": mechanical.ambiguous_spans[0]["id"],
                "reading": "TOO",
                "type": "english",
                "confidence": 0.82,
            }
        ],
        "uncertain": [],
    }

    resolved = AmbiguityResolver(
        ChoiceProvider(response),
        system_prompt="choose",
    ).resolve(mechanical)

    assert resolved.normalized_for_stage2 == "と"


def test_local_ai_payload_contains_segment_plan_and_mechanical_result() -> None:
    prepared = _prepare_local_ai_input("rakuten | ka do | nyuryok")
    payload = json.loads(_input_payload(prepared))

    assert payload["task"] == "resolve_ambiguous_readings_only"
    assert "".join(segment["raw"] for segment in payload["segment_plan"]) == prepared.masked.text
    assert payload["mechanical_normalized"].startswith("らくてん | か ど |")
    assert payload["suspicious_spans"][0]["raw"] == "nyuryok"
