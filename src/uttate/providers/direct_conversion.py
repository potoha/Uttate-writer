from __future__ import annotations

from importlib import resources

from uttate.input_rules import parse_protected_input, protected_terms_prompt
from uttate.models import JsonObject

CONVERSION_SCHEMA: JsonObject = {
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
            },
        },
        "uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "candidates": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["raw", "candidates", "reason"],
            },
        },
    },
    "required": ["candidates", "uncertain"],
}


def load_system_prompt() -> str:
    """Load the provider-neutral prompt used by all direct conversion providers."""

    return (
        resources.files("uttate.prompts")
        .joinpath("api_direct_converter_system.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def build_conversion_prompt(
    system_prompt: str,
    *,
    raw_text: str,
    previous_context: str,
    candidate_count: int,
) -> str:
    """Build the user-visible payload shared by Gemini/OpenAI/compatible providers."""

    context = previous_context.strip() or "(なし)"
    protected_input = parse_protected_input(raw_text.strip())
    return (
        f"{system_prompt}\n\n"
        f"候補数: {candidate_count}\n\n"
        f"直前の文脈:\n{context}\n\n"
        f"{protected_terms_prompt(protected_input.terms)}\n\n"
        f"入力:\n{protected_input.text}\n"
    )
