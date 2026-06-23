from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from uttate.models import JsonObject


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Provider-neutral result consumed by the asynchronous conversion queue."""

    normalized: str
    candidate_1: str
    candidate_2: str
    segments: tuple[JsonObject, ...] = ()
    dictionary_candidates: tuple[JsonObject, ...] = ()
    uncertain: tuple[JsonObject, ...] = ()


class ConversionProvider(Protocol):
    """Synchronous conversion boundary executed outside the UI thread."""

    def convert(self, raw_text: str) -> ConversionResult:
        """Convert one raw chunk into reviewable candidates."""
        ...
