from __future__ import annotations

from uttate.config import ProviderSettings
from uttate.providers.base import ConversionProvider
from uttate.providers.gemini import GeminiProvider
from uttate.providers.mock import MockProvider
from uttate.providers.openai import OpenAIProvider
from uttate.providers.openai_compatible import OpenAICompatibleProvider


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
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_seconds=settings.timeout_seconds,
            endpoint=f"{settings.openai_base_url.rstrip('/')}/responses",
        )
    if settings.type in {"lmstudio", "openai_compatible"}:
        return OpenAICompatibleProvider(
            base_url=settings.compatible_base_url,
            api_key=settings.compatible_api_key,
            model=settings.compatible_model,
            provider_name=settings.type,
            timeout_seconds=settings.timeout_seconds,
            reasoning_effort="none" if settings.type == "lmstudio" else None,
        )
    raise ValueError(f"Unsupported provider type: {settings.type}")
