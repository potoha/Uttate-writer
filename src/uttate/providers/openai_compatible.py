from __future__ import annotations

from typing import Any

import httpx

from uttate.models import JsonObject
from uttate.pipeline.response_parser import parse_provider_result
from uttate.providers.base import ConversionProvider, ProviderError, ProviderResult
from uttate.providers.direct_conversion import (
    CONVERSION_SCHEMA,
    build_conversion_prompt,
    load_system_prompt,
)


class OpenAICompatibleProvider(ConversionProvider):
    """OpenAI-compatible Chat Completions provider.

    LM Studio, OpenRouter, and many local/hosted adapters expose this shape. The UI can
    choose "LM Studio" while the code stays generic enough to reuse in main later.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        provider_name: str = "openai_compatible",
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        if not base_url.strip():
            raise ProviderError("OpenAI-compatible base URL is not set.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")

        self.base_url = f"{base_url.rstrip('/')}/"
        self.api_key = api_key
        self.model = model
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self.reasoning_effort = reasoning_effort
        self._system_prompt = load_system_prompt()

    def convert(
        self,
        raw_text: str,
        *,
        previous_context: str = "",
        candidate_count: int = 2,
    ) -> ProviderResult:
        if not raw_text.strip():
            raise ValueError("raw_text must not be empty.")
        if candidate_count <= 0:
            raise ValueError("candidate_count must be positive.")

        model = self._resolved_model()
        payload = self._build_payload(model, raw_text, previous_context, candidate_count)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post("chat/completions", headers=headers, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            message = f"{self.provider_name} timed out after {self.timeout_seconds:g} seconds."
            raise ProviderError(message) from error
        except httpx.HTTPStatusError as error:
            raise ProviderError(_http_error_message(self.provider_name, error.response)) from error
        except httpx.RequestError as error:
            raise ProviderError(f"Could not connect to {self.provider_name}.") from error

        response_data = _response_json(response, self.provider_name)
        output_text = _message_text(response_data, self.provider_name)
        return parse_provider_result(
            output_text,
            provider=self.provider_name,
            model=model,
            candidate_count=candidate_count,
            raw_response=output_text,
        )

    def _resolved_model(self) -> str:
        if self.model.strip():
            return self.model
        model = self._first_available_model()
        self.model = model
        return model

    def _first_available_model(self) -> str:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self._transport,
                headers=headers,
            ) as client:
                response = client.get("models")
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderError(f"{self.provider_name} model lookup timed out.") from error
        except httpx.HTTPStatusError as error:
            raise ProviderError(_http_error_message(self.provider_name, error.response)) from error
        except httpx.RequestError as error:
            raise ProviderError(f"Could not look up {self.provider_name} models.") from error

        data = _response_json(response, self.provider_name)
        models = data.get("data")
        if not isinstance(models, list) or not models:
            raise ProviderError(f"{self.provider_name} did not report any loaded models.")
        first = models[0]
        if not isinstance(first, dict) or not isinstance(first.get("id"), str):
            raise ProviderError(f"{self.provider_name} model response had an invalid shape.")
        return first["id"]

    def _build_payload(
        self,
        model: str,
        raw_text: str,
        previous_context: str,
        candidate_count: int,
    ) -> JsonObject:
        payload: JsonObject = {
            "model": model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": build_conversion_prompt(
                        "",
                        raw_text=raw_text,
                        previous_context=previous_context,
                        candidate_count=candidate_count,
                    ).strip(),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "uttate_conversion_result",
                    "strict": True,
                    "schema": CONVERSION_SCHEMA,
                },
            },
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload


def _response_json(response: httpx.Response, provider_label: str) -> JsonObject:
    try:
        decoded: Any = response.json()
    except ValueError as error:
        raise ProviderError(f"{provider_label} response was not valid JSON.") from error
    if not isinstance(decoded, dict):
        raise ProviderError(f"{provider_label} response root must be an object.")
    return decoded


def _message_text(response_data: JsonObject, provider_label: str) -> str:
    try:
        message = response_data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise ProviderError(f"{provider_label} response did not include a message.") from error

    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, dict):
        return _json_dump(content)
    if isinstance(content, list):
        text = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
        if text.strip():
            return text
    if isinstance(content, str) and content.strip():
        return content

    reasoning_content = message.get("reasoning_content") if isinstance(message, dict) else None
    if isinstance(reasoning_content, str) and reasoning_content.strip():
        return reasoning_content
    raise ProviderError(f"{provider_label} response message text was empty.")


def _json_dump(value: JsonObject) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _http_error_message(provider_label: str, response: httpx.Response) -> str:
    detail = response.text.strip().replace("\n", " ")[:300]
    return f"{provider_label} returned HTTP {response.status_code}: {detail}"
