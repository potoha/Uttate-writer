import pytest

from uttate.conversion.response_parser import parse_provider_result


def test_response_parser_accepts_plain_json() -> None:
    result = parse_provider_result(
        '{"candidates":[{"label":"faithful","text":"本文"}],"uncertain":[]}',
        provider="test",
        model="model",
    )

    assert result.candidates[0].text == "本文"


def test_response_parser_accepts_fenced_json() -> None:
    result = parse_provider_result(
        '```json\n{"candidates":[{"label":"faithful","text":"本文"}],"uncertain":[]}\n```',
        provider="test",
        model="model",
    )

    assert result.candidates[0].label == "faithful"


def test_response_parser_extracts_json_from_extra_text() -> None:
    result = parse_provider_result(
        'Here is JSON: {"candidates":[{"label":"faithful","text":"本文"}],"uncertain":[]}',
        provider="test",
        model="model",
    )

    assert result.candidates[0].text == "本文"


def test_response_parser_rejects_empty_candidates() -> None:
    with pytest.raises(RuntimeError, match="at least one candidate"):
        parse_provider_result('{"candidates":[],"uncertain":[]}', provider="test", model="model")
