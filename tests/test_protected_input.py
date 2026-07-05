from uttate.input_rules import (
    ProtectedKind,
    parse_protected_input,
    romaji_to_hiragana,
    romaji_to_katakana,
)
from uttate.providers.direct_conversion import build_conversion_prompt


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


def test_romaji_helpers_cover_tag_conversions() -> None:
    assert romaji_to_katakana("dedodamu") == "デドダム"
    assert romaji_to_hiragana("tokiori") == "ときおり"


def test_conversion_prompt_includes_protected_terms_and_clean_input() -> None:
    prompt = build_conversion_prompt(
        "system",
        raw_text="\\dedodamu\\ to =English= to $tokiori$",
        previous_context="",
        candidate_count=2,
    )

    assert "katakana_name: `dedodamu` -> `デドダム`" in prompt
    assert "preserve_english: `English` -> `English`" in prompt
    assert "hiragana: `tokiori` -> `ときおり`" in prompt
    assert "入力:\nデドダム to English to ときおり" in prompt
