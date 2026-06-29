import httpx
import pytest

from uttate.config import ProviderSettings
from uttate.providers.base import Candidate, ProviderResult
from uttate.providers.factory import create_conversion_provider
from uttate.providers.gemini import GeminiProvider
from uttate.providers.mock import MockProvider


def test_provider_result_requires_at_least_one_candidate() -> None:
    with pytest.raises(ValueError, match="at least one candidate"):
        ProviderResult(candidates=())


def test_candidate_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="candidate text"):
        Candidate("faithful", "")


def test_mock_provider_returns_project_b_candidates() -> None:
    result = MockProvider(delay_seconds=0).convert("AIdenyuuryokuwosaisekkeisuru.")

    assert result.provider == "mock"
    assert [candidate.label for candidate in result.candidates] == ["faithful", "natural"]
    assert result.candidates[0].text == "AIで入力を再設計する。"


def test_factory_keeps_unimplemented_api_providers_explicit() -> None:
    provider = create_conversion_provider(ProviderSettings(type="openai"))

    with pytest.raises(RuntimeError, match="not implemented yet"):
        provider.convert("rough")


def test_factory_creates_gemini_provider() -> None:
    provider = create_conversion_provider(
        ProviderSettings(type="gemini", gemini_api_key="dummy-key", gemini_model="gemini-test")
    )

    assert isinstance(provider, GeminiProvider)


def test_gemini_provider_posts_structured_request_and_parses_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://generativelanguage.googleapis.com/v1beta/interactions"
        assert request.headers["x-goog-api-key"] == "dummy-1234567890"
        payload = request.read().decode("utf-8")
        assert "gemini-test" in payload
        assert "AIdenyuuryokuwosaisekkeisuru." in payload
        return httpx.Response(
            200,
            json={
                "output_text": (
                    '{"candidates":['
                    '{"label":"faithful","text":"AIで入力を再設計する。"},'
                    '{"label":"natural","text":"AIを使って入力を再設計する。"}'
                    '],"uncertain":[]}'
                )
            },
        )

    provider = GeminiProvider(
        api_key="dummy-1234567890",
        model="gemini-test",
        transport=httpx.MockTransport(handler),
    )

    result = provider.convert("AIdenyuuryokuwosaisekkeisuru.", previous_context="前文")

    assert result.provider == "gemini"
    assert result.model == "gemini-test"
    assert result.candidates[0].text == "AIで入力を再設計する。"


def test_gemini_provider_requires_api_key() -> None:
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiProvider(api_key="", model="gemini-test")


def test_gemini_provider_turns_http_errors_into_provider_errors() -> None:
    provider = GeminiProvider(
        api_key="dummy-1234567890",
        model="gemini-test",
        transport=httpx.MockTransport(lambda request: httpx.Response(403, text="bad key")),
    )

    with pytest.raises(RuntimeError, match="HTTP 403"):
        provider.convert("rough")
