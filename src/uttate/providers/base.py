from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from uttate.models import JsonObject


@dataclass(frozen=True, slots=True)
class Candidate:
    """One reviewable conversion candidate returned by any Project B provider."""

    label: str
    text: str

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("candidate label must not be empty.")
        if not self.text.strip():
            raise ValueError("candidate text must not be empty.")


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """Optional usage metadata; providers may fill this later without changing UI code."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Provider-neutral direct conversion result consumed by the async queue.

    Project B intentionally keeps the UI ignorant of Gemini/OpenAI/local details.
    Any provider may be swapped in as long as it returns this small contract.
    """

    candidates: tuple[Candidate, ...]
    uncertain: tuple[JsonObject, ...] = ()
    provider: str = ""
    model: str = ""
    raw_response: str | None = None
    usage: ProviderUsage | None = None

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("provider result must include at least one candidate.")


class ProviderError(RuntimeError):
    """Base class for user-visible provider failures."""


class ConversionProvider(Protocol):
    """Synchronous conversion boundary executed outside the UI thread.

    Providers receive previous_context even when a test double ignores it. Keeping it in the
    contract prevents Gemini/OpenAI support from leaking provider-specific parameters into UI.
    """

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        """Convert one raw chunk into reviewable candidates."""
        ...
