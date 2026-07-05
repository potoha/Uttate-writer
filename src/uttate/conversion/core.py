from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from uttate.providers.base import ConversionProvider, ProviderResult


@dataclass(frozen=True, slots=True)
class ConversionRequest:
    """Provider-neutral request object for conversion cores.

    Main-derived local conversion can implement this contract without coupling
    itself to Gemini/OpenAI payload builders or UI queue details.
    """

    raw_text: str
    previous_context: str = ""
    candidate_count: int = 2

    def __post_init__(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("raw_text must not be empty.")
        if self.candidate_count <= 0:
            raise ValueError("candidate_count must be positive.")


class ConversionCore(Protocol):
    """Stable boundary for not-local and main-derived conversion implementations."""

    name: str

    def convert_request(self, request: ConversionRequest) -> ProviderResult:
        """Convert one normalized request into reviewable candidates."""
        ...


class DirectProviderCore:
    """Adapter that exposes the existing provider contract as a conversion core."""

    def __init__(self, provider: ConversionProvider, *, name: str | None = None) -> None:
        self.provider = provider
        self.name = name or getattr(provider, "name", provider.__class__.__name__)

    def convert_request(self, request: ConversionRequest) -> ProviderResult:
        return self.provider.convert(
            request.raw_text,
            previous_context=request.previous_context,
            candidate_count=request.candidate_count,
        )
