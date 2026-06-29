import httpx
import pytest

from uttate.config import ProviderSettings
from uttate.providers.base import Candidate, ProviderResult
from uttate.providers.factory import create_conversion_provider
from uttate.providers.gemini import GeminiProvider
from uttate.providers.mock import MockProvider
from uttate.providers.openai import OpenAIProvider
from uttate.providers.openai_compatible import OpenAICompatibleProvider


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
    with pytest.raises(ValueError, match="Unsupported provider"):
        create_conversion_provider(ProviderSettings(type="missing"))


def test_factory_creates_gemini_provider() -> None:
    provider = create_conversion_provider(
        ProviderSettings(type="gemini", gemini_api_key="dummy-key", gemini_model="gemini-test")
    )

    assert isinstance(provider, GeminiProvider)


def test_factory_creates_openai_provider() -> None:
    provider = create_conversion_provider(
        ProviderSettings(type="openai", openai_api_key="dummy-key", openai_model="gpt-test")
    )

    assert isinstance(provider, OpenAIProvider)


def test_factory_creates_lmstudio_compatible_provider() -> None:
    provider = create_conversion_provider(ProviderSettings(type="lmstudio"))

    assert isinstance(provider, OpenAICompatibleProvider)


def test_gemini_provider_posts_structured_request_and_parses_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (
            request.url
            == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "dummy-1234567890"
        payload = request.read().decode("utf-8")
        assert "AIdenyuuryokuwosaisekkeisuru." in payload
        assert "generationConfig" in payload
        assert "responseMimeType" in payload
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"candidates":['
                                        '{"label":"faithful","text":"AIで入力を再設計する。"},'
                                        '{"label":"natural","text":"AIを使って入力を再設計する。"}'
                                        '],"uncertain":[]}'
                                    )
                                }
                            ]
                        }
                    }
                ]
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


def test_openai_provider_posts_responses_request_and_parses_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer dummy-openai"
        payload = request.read().decode("utf-8")
        assert "gpt-test" in payload
        assert "AIdenyuuryokuwosaisekkeisuru." in payload
        assert "json_schema" in payload
        return httpx.Response(
            200,
            json={
                "output_text": (
                    '{"candidates":[{"label":"faithful","text":"AIで入力を再設計する。"}],'
                    '"uncertain":[]}'
                )
            },
        )

    provider = OpenAIProvider(
        api_key="dummy-openai",
        model="gpt-test",
        transport=httpx.MockTransport(handler),
    )

    result = provider.convert("AIdenyuuryokuwosaisekkeisuru.")

    assert result.provider == "openai"
    assert result.model == "gpt-test"
    assert result.candidates[0].text == "AIで入力を再設計する。"


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIProvider(api_key="", model="gpt-test")


def test_openai_compatible_provider_posts_chat_completion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://local.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer compat-key"
        payload = request.read().decode("utf-8")
        assert "local-model" in payload
        assert "response_format" in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"candidates":[{"label":"faithful","text":"本文"}],"uncertain":[]}'
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="http://local.test/v1",
        api_key="compat-key",
        model="local-model",
        provider_name="lmstudio",
        transport=httpx.MockTransport(handler),
    )

    result = provider.convert("rough")

    assert result.provider == "lmstudio"
    assert result.model == "local-model"
    assert result.candidates[0].text == "本文"


def test_openai_compatible_provider_auto_detects_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "loaded-model"}]})
        assert request.url.path.endswith("/chat/completions")
        assert '"model":"loaded-model"' in request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"candidates":[{"label":"faithful","text":"本文"}],"uncertain":[]}'
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="http://local.test/v1",
        api_key="",
        model="",
        provider_name="lmstudio",
        transport=httpx.MockTransport(handler),
    )

    result = provider.convert("rough")

    assert result.model == "loaded-model"
