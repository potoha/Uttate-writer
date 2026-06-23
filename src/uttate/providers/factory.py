from __future__ import annotations

from uttate.config import ProviderSettings
from uttate.providers.base import LLMProvider
from uttate.providers.lmstudio import LMStudioProvider
from uttate.providers.mock import MockProvider
from uttate.providers.openai_compatible import OpenAICompatibleProvider


def create_llm_provider(settings: ProviderSettings) -> LLMProvider:
    if settings.type == "lmstudio":
        return LMStudioProvider(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            reasoning_effort=settings.reasoning_effort,
        )
    if settings.type == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            reasoning_effort=settings.reasoning_effort or None,
        )
    if settings.type == "mock":
        return MockProvider()
    raise ValueError(f"Unsupported provider type: {settings.type}")
