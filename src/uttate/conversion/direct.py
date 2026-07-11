from __future__ import annotations

from importlib import resources

from uttate.input_rules import (
    MaskedProtectedInput,
    mask_protected_input,
    protected_masks_prompt,
)
from uttate.models import JsonObject
from uttate.providers.base import Candidate, ProviderError, ProviderResult

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
    """Build the user-visible payload shared by Gemini/OpenAI direct providers."""

    context = previous_context.strip() or "(なし)"
    protected_input = mask_protected_input(raw_text.strip())
    return (
        f"{system_prompt}\n\n"
        f"候補数: {candidate_count}\n\n"
        f"直前の文脈:\n{context}\n\n"
        f"{protected_masks_prompt(protected_input.masks)}\n\n"
        f"入力:\n{protected_input.text}\n"
    )


def prepare_conversion_prompt(
    system_prompt: str,
    *,
    raw_text: str,
    previous_context: str,
    candidate_count: int,
) -> tuple[str, MaskedProtectedInput]:
    masked = mask_protected_input(raw_text.strip())
    context = previous_context.strip() or "(なし)"
    prompt = (
        f"{system_prompt}\n\n"
        f"候補数: {candidate_count}\n\n"
        f"直前の文脈:\n{context}\n\n"
        f"{protected_masks_prompt(masked.masks)}\n\n"
        f"入力:\n{masked.text}\n"
    )
    return prompt, masked


def restore_masked_provider_result(
    result: ProviderResult,
    masked: MaskedProtectedInput,
) -> ProviderResult:
    return ProviderResult(
        candidates=tuple(
            Candidate(candidate.label, _restore_masked_candidate(candidate.text, masked))
            for candidate in result.candidates
        ),
        uncertain=tuple(_restore_uncertain(item, masked) for item in result.uncertain),
        provider=result.provider,
        model=result.model,
        raw_response=result.raw_response,
        usage=result.usage,
    )


def _restore_masked_candidate(text: str, masked: MaskedProtectedInput) -> str:
    """Restore a provider candidate only when every protected term survived intact."""

    for mask in masked.masks:
        count = text.count(mask.placeholder)
        if count != 1:
            raise ProviderError(
                "Provider candidate must contain each protected placeholder exactly once; "
                f"{mask.placeholder} occurred {count} times."
            )
    return masked.restore(text)


def _restore_uncertain(value: JsonObject, masked: MaskedProtectedInput) -> JsonObject:
    restored: JsonObject = {}
    for key, item in value.items():
        if isinstance(item, str):
            restored[key] = masked.restore(item)
        elif isinstance(item, list):
            restored[key] = [
                masked.restore(candidate) if isinstance(candidate, str) else candidate
                for candidate in item
            ]
        else:
            restored[key] = item
    return restored
