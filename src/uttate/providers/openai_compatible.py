from __future__ import annotations

import json
from typing import Any

import httpx

from uttate.models import JsonObject
from uttate.providers.base import LLMProvider


class LLMProviderError(RuntimeError):
    """Base error for user-visible provider failures."""


class ProviderConnectionError(LLMProviderError):
    """The configured provider could not be reached."""


class ProviderTimeoutError(LLMProviderError):
    """The provider did not respond before the configured timeout."""


class ProviderResponseError(LLMProviderError):
    """The provider returned an HTTP or response-format error."""


class OpenAICompatibleProvider(LLMProvider):
    """Structured JSON client for OpenAI-compatible chat-completion servers."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        reasoning_effort: str | None = None,
        max_tokens: int = 2048,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be empty.")
        if not model.strip():
            raise ValueError("model must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive.")

        self.base_url = f"{base_url.rstrip('/')}/"
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens
        self._transport = transport

    def complete_json(
        self,
        messages: list[JsonObject],
        schema: JsonObject | None = None,
    ) -> JsonObject:
        if not messages:
            raise ValueError("messages must not be empty.")

        payload: JsonObject = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "uttate_response",
                    "strict": True,
                    "schema": schema,
                },
            }

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            with self._create_client(headers) as client:
                response = client.post("chat/completions", json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(
                f"The provider timed out after {self.timeout_seconds:g} seconds."
            ) from error
        except httpx.HTTPStatusError as error:
            detail = error.response.text.strip().replace("\n", " ")[:300]
            raise ProviderResponseError(
                f"The provider returned HTTP {error.response.status_code}: {detail}"
            ) from error
        except httpx.RequestError as error:
            raise ProviderConnectionError(
                f"Could not connect to the provider at {self.base_url}"
            ) from error

        try:
            response_data: Any = response.json()
        except ValueError as error:
            raise ProviderResponseError("The provider response was not valid JSON.") from error

        content = self._message_content(response_data)
        try:
            decoded: Any = content if isinstance(content, dict) else json.loads(content)
        except (TypeError, json.JSONDecodeError) as error:
            raise ProviderResponseError(
                "The assistant message did not contain a valid JSON object."
            ) from error
        if not isinstance(decoded, dict):
            raise ProviderResponseError("The assistant JSON response must be an object.")
        return decoded

    def _create_client(self, headers: dict[str, str] | None = None) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout_seconds,
            transport=self._transport,
        )

    @staticmethod
    def _message_content(response_data: Any) -> str | JsonObject:
        try:
            message = response_data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderResponseError(
                "The provider response did not contain an assistant message."
            ) from error

        content = message.get("content")
        if isinstance(content, dict):
            return content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        if not isinstance(content, str) or not content.strip():
            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content.strip():
                content = reasoning_content
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError("The assistant message content was empty.")
        return _strip_json_fence(content.strip())


def _strip_json_fence(content: str) -> str:
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return content
