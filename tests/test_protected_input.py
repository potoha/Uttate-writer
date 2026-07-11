import pytest

from uttate.conversion.direct import (
    build_conversion_prompt,
    restore_masked_provider_result,
)
from uttate.input_rules import (
    ProtectedKind,
    mask_protected_input,
    parse_protected_input,
    romaji_to_hiragana,
    romaji_to_katakana,
)
from uttate.providers.base import Candidate, ProviderError, ProviderResult


def test_katakana_name_tag_forces_katakana() -> None:
    parsed = parse_protected_input("\\dedodamu\\ wo tsukau")

    assert parsed.text == "デドダム wo tsukau"
    assert parsed.terms[0].kind == ProtectedKind.KATAKANA_NAME
    assert parsed.terms[0].source == "dedodamu"
    assert parsed.terms[0].replacement == "デドダム"


def test_english_and_hiragana_tags_are_protected() -> None:
    parsed = parse_protected_input("= English= to $tokiori$")

    assert parsed.text == "English to ときおり"
    assert [term.kind for term in parsed.terms] == [
        ProtectedKind.PRESERVE_ENGLISH,
        ProtectedKind.HIRAGANA,
    ]
    assert [term.replacement for term in parsed.terms] == ["English", "ときおり"]


def test_double_markers_escape_to_literal_characters() -> None:
    parsed = parse_protected_input("\\\\dedodamu\\\\ ==English== $$tokiori$$")

    assert parsed.text == "\\dedodamu\\ =English= $tokiori$"
    assert parsed.terms == ()


def test_unclosed_tag_is_left_as_literal_text() -> None:
    parsed = parse_protected_input("\\dedodamu to =English to $tokiori")

    assert parsed.text == "\\dedodamu to =English to $tokiori"
    assert parsed.terms == ()


def test_protected_input_can_be_masked_and_restored() -> None:
    masked = mask_protected_input("\\dedodamu\\ to =English= to $tokiori$")

    assert masked.text == (
        "__UTTATE_PROTECTED_0__ to __UTTATE_PROTECTED_1__ to __UTTATE_PROTECTED_2__"
    )
    assert [mask.kind for mask in masked.masks] == [
        ProtectedKind.KATAKANA_NAME,
        ProtectedKind.PRESERVE_ENGLISH,
        ProtectedKind.HIRAGANA,
    ]
    assert masked.restore("__UTTATE_PROTECTED_0__ and __UTTATE_PROTECTED_2__") == (
        "デドダム and ときおり"
    )


def test_romaji_helpers_cover_tag_conversions() -> None:
    assert romaji_to_katakana("dedodamu") == "デドダム"
    assert romaji_to_hiragana("tokiori") == "ときおり"
    assert romaji_to_hiragana("in+you") == "いんよう"
    assert romaji_to_hiragana("in＋you") == "いんよう"


def test_conversion_prompt_includes_protected_terms_and_clean_input() -> None:
    prompt = build_conversion_prompt(
        "system",
        raw_text="\\dedodamu\\ to =English= to $tokiori$",
        previous_context="",
        candidate_count=2,
    )

    assert "dedodamu" not in prompt
    assert "English" not in prompt
    assert "tokiori" not in prompt
    assert "デドダム" not in prompt
    assert "katakana_name: `__UTTATE_PROTECTED_0__`" in prompt
    assert "preserve_english: `__UTTATE_PROTECTED_1__`" in prompt
    assert "hiragana: `__UTTATE_PROTECTED_2__`" in prompt
    assert (
        "入力:\n__UTTATE_PROTECTED_0__ to __UTTATE_PROTECTED_1__ to __UTTATE_PROTECTED_2__"
    ) in prompt


@pytest.mark.parametrize(
    "candidate_text",
    [
        "placeholder omitted",
        "__UTTATE_PROTECTED_0__ and __UTTATE_PROTECTED_0__",
        "__uttate_protected_0__",
    ],
)
def test_protected_placeholder_must_survive_exactly_once(candidate_text: str) -> None:
    masked = mask_protected_input("=English=")
    result = ProviderResult(candidates=(Candidate("faithful", candidate_text),))

    with pytest.raises(ProviderError, match="exactly once"):
        restore_masked_provider_result(result, masked)


def test_protected_placeholder_is_restored_after_validation() -> None:
    masked = mask_protected_input("=English=")
    result = ProviderResult(candidates=(Candidate("faithful", "Use __UTTATE_PROTECTED_0__ once."),))

    restored = restore_masked_provider_result(result, masked)

    assert restored.candidates[0].text == "Use English once."
