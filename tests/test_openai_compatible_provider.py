from __future__ import annotations

import json

import httpx
import pytest

from uttate.providers.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderConnectionError,
    ProviderResponseError,
    ProviderTimeoutError,
)

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def provider_for(handler: httpx.MockTransport) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="http://provider.test/v1",
        api_key="secret-key",
        model="test-model",
        timeout_seconds=2,
        reasoning_effort="none",
        transport=handler,
    )


def test_complete_json_sends_json_schema_and_decodes_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == httpx.URL("http://provider.test/v1/chat/completions")
        assert request.headers["authorization"] == "Bearer secret-key"
        assert payload["model"] == "test-model"
        assert payload["reasoning_effort"] == "none"
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["schema"] == SCHEMA
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    provider = provider_for(httpx.MockTransport(handler))

    assert provider.complete_json([{"role": "user", "content": "health"}], SCHEMA) == {"ok": True}


def test_reasoning_content_is_used_when_content_is_empty() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "", "reasoning_content": '{"ok": true}'}}]},
        )
    )

    assert provider_for(transport).complete_json([{"role": "user", "content": "x"}]) == {"ok": True}


def test_markdown_json_fence_is_tolerated_for_compatible_servers() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}]},
        )
    )

    assert provider_for(transport).complete_json([{"role": "user", "content": "x"}]) == {"ok": True}


def test_timeout_is_converted_to_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderTimeoutError, match="2 seconds"):
        provider_for(httpx.MockTransport(handler)).complete_json([{"role": "user", "content": "x"}])


def test_connection_failure_is_converted_to_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(ProviderConnectionError, match="provider.test"):
        provider_for(httpx.MockTransport(handler)).complete_json([{"role": "user", "content": "x"}])


def test_http_failure_includes_status_without_api_key() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"error": "unavailable"})
    )

    with pytest.raises(ProviderResponseError, match="HTTP 503") as error:
        provider_for(transport).complete_json([{"role": "user", "content": "x"}])

    assert "secret-key" not in str(error.value)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, text="not-json"), "not valid JSON"),
        (httpx.Response(200, json={"choices": []}), "assistant message"),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]}),
            "must be an object",
        ),
    ],
)
def test_malformed_provider_responses_are_rejected(response: httpx.Response, message: str) -> None:
    transport = httpx.MockTransport(lambda request: response)

    with pytest.raises(ProviderResponseError, match=message):
        provider_for(transport).complete_json([{"role": "user", "content": "x"}])
