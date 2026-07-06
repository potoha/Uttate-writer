from __future__ import annotations

import json
import threading
from typing import Any

import httpx

from uttate.conversion.local_ai import (
    LocalAILLMProvider,
    ReadingNormalizationProvider,
    ReadingNormalizer,
)
from uttate.models import JsonObject
from uttate.prompts.registry import LocalAIPromptRegistry
from uttate.providers.base import ProviderResult


class LocalAIProviderError(RuntimeError):
    """Base error for user-visible local AI provider failures."""


class ProviderConnectionError(LocalAIProviderError):
    """The configured provider could not be reached."""


class ProviderTimeoutError(LocalAIProviderError):
    """The provider did not respond before the configured timeout."""


class ProviderResponseError(LocalAIProviderError):
    """The provider returned an HTTP or response-format error."""


class OpenAICompatibleJSONClient(LocalAILLMProvider):
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
            decoded: Any = content if isinstance(content, dict) else _decode_json_object(content)
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


class LMStudioJSONClient(OpenAICompatibleJSONClient):
    """LM Studio preset using its local OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        model: str = "",
        base_url: str = "http://127.0.0.1:1234/v1",
        api_key: str = "lm-studio",
        timeout_seconds: float = 60.0,
        reasoning_effort: str | None = "none",
        max_tokens: int = 2048,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._auto_detect_model = not model.strip()
        self._model_lock = threading.Lock()
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            model=model or "__auto_detect__",
            timeout_seconds=timeout_seconds,
            reasoning_effort=reasoning_effort,
            max_tokens=max_tokens,
            transport=transport,
        )

    def complete_json(
        self,
        messages: list[JsonObject],
        schema: JsonObject | None = None,
    ) -> JsonObject:
        self.ensure_model()
        return super().complete_json(messages, schema)

    def ensure_model(self) -> str:
        if self._auto_detect_model:
            with self._model_lock:
                if self._auto_detect_model:
                    self.model = self._discover_loaded_model()
                    self._auto_detect_model = False
        return self.model

    def _discover_loaded_model(self) -> str:
        try:
            with self._create_client() as client:
                response = client.get("models")
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(
                f"LM Studio model discovery timed out after {self.timeout_seconds:g} seconds."
            ) from error
        except httpx.HTTPStatusError as error:
            raise ProviderResponseError(
                f"LM Studio model discovery returned HTTP {error.response.status_code}."
            ) from error
        except httpx.RequestError as error:
            raise ProviderConnectionError(
                f"Could not connect to LM Studio at {self.base_url}"
            ) from error

        try:
            response_data = response.json()
            model_ids = [
                item["id"]
                for item in response_data["data"]
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderResponseError("LM Studio returned an invalid model list.") from error
        if not model_ids:
            raise ProviderResponseError("LM Studio has no loaded model.")
        return model_ids[0]


class LocalAIProvider(ReadingNormalizationProvider):
    """Project B provider adapter for the main-derived local Stage 1 normalizer."""

    name = "local_ai"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1234/v1",
        api_key: str = "lm-studio",
        model: str = "",
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        prompt_registry: LocalAIPromptRegistry | None = None,
    ) -> None:
        client = LMStudioJSONClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        self.client = client
        self.prompt_registry = prompt_registry or LocalAIPromptRegistry.load()
        if model.strip():
            self.prompt_registry.ensure_model_profile(model)
        super().__init__(
            ReadingNormalizer(
                client,
                system_prompt=self.prompt_registry.prompt_for_model(model),
            )
        )

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        model = ""
        try:
            detected_model = self.client.ensure_model()
        except LocalAIProviderError:
            detected_model = ""
        if detected_model:
            self.prompt_registry.ensure_model_profile(detected_model)
            self.normalizer.system_prompt = self.prompt_registry.prompt_for_model(detected_model)
            model = detected_model

        result = self.normalizer.convert_to_provider_result(
            raw_text,
            previous_context=previous_context,
            candidate_count=candidate_count,
            model=model,
        )
        return ProviderResult(
            candidates=result.candidates,
            uncertain=result.uncertain,
            provider=self.name,
            model=model or result.model,
            raw_response=result.raw_response,
            usage=result.usage,
        )


def _strip_json_fence(content: str) -> str:
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return content


def _decode_json_object(content: str) -> JsonObject:
    stripped = _strip_json_fence(content.strip())
    for candidate in (stripped, _extract_first_json_object(stripped)):
        try:
            decoded: Any = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    raise json.JSONDecodeError("No JSON object found", stripped, 0)


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return text

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text
