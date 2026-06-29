from __future__ import annotations

from uttate.config import ProviderSettings
from uttate.providers.base import ConversionProvider, ProviderError
from uttate.providers.gemini import GeminiProvider
from uttate.providers.mock import MockProvider


class UnimplementedProvider:
    """Explicit placeholder for providers planned after the current provider milestone.

    Keeping a clear failure is friendlier for OSS users than silently falling back to Mock:
    if someone selects an unfinished provider, they should see why the chunk failed.
    """

    def __init__(self, provider_type: str) -> None:
        self.provider_type = provider_type

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ):
        del raw_text, previous_context, candidate_count
        raise ProviderError(
            f"{self.provider_type} provider is not implemented yet in this cleanup step."
        )


def create_conversion_provider(settings: ProviderSettings) -> ConversionProvider:
    """Create the direct-conversion provider selected by Project B settings."""

    if settings.type == "mock":
        return MockProvider()
    if settings.type == "gemini":
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.timeout_seconds,
        )
    if settings.type == "openai":
        return UnimplementedProvider(settings.type)
    raise ValueError(f"Unsupported provider type: {settings.type}")
