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

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIProvider(ConversionProvider):
    """OpenAI Responses API provider for Project B direct conversion."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        endpoint: str = OPENAI_RESPONSES_URL,
    ) -> None:
        if not api_key.strip():
            raise ProviderError("OPENAI_API_KEY is not set.")
        if not model.strip():
            raise ProviderError("OPENAI_MODEL is not set.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")

        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.endpoint = endpoint
        self._transport = transport
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

        payload = self._build_payload(raw_text, previous_context, candidate_count)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.post(self.endpoint, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            message = f"OpenAI timed out after {self.timeout_seconds:g} seconds."
            raise ProviderError(message) from error
        except httpx.HTTPStatusError as error:
            raise ProviderError(_http_error_message("OpenAI API", error.response)) from error
        except httpx.RequestError as error:
            raise ProviderError("Could not connect to OpenAI API.") from error

        response_data = _response_json(response, "OpenAI")
        output_text = _output_text(response_data, "OpenAI")
        return parse_provider_result(
            output_text,
            provider=self.name,
            model=self.model,
            candidate_count=candidate_count,
            raw_response=output_text,
        )

    def _build_payload(
        self,
        raw_text: str,
        previous_context: str,
        candidate_count: int,
    ) -> JsonObject:
        return {
            "model": self.model,
            "instructions": self._system_prompt,
            "input": build_conversion_prompt(
                "",
                raw_text=raw_text,
                previous_context=previous_context,
                candidate_count=candidate_count,
            ).strip(),
            "temperature": 0.2,
            "max_output_tokens": 1024,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "uttate_conversion_result",
                    "schema": CONVERSION_SCHEMA,
                    "strict": True,
                }
            },
        }


def _response_json(response: httpx.Response, provider_label: str) -> JsonObject:
    try:
        decoded: Any = response.json()
    except ValueError as error:
        raise ProviderError(f"{provider_label} response was not valid JSON.") from error
    if not isinstance(decoded, dict):
        raise ProviderError(f"{provider_label} response root must be an object.")
    return decoded


def _output_text(response_data: JsonObject, provider_label: str) -> str:
    output_text = response_data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    try:
        output = response_data["output"]
    except KeyError as error:
        raise ProviderError(f"{provider_label} response did not include output_text.") from error
    if not isinstance(output, list):
        raise ProviderError(f"{provider_label} response output must be an array.")

    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    joined = "".join(texts)
    if not joined.strip():
        raise ProviderError(f"{provider_label} response text was empty.")
    return joined


def _http_error_message(provider_label: str, response: httpx.Response) -> str:
    detail = response.text.strip().replace("\n", " ")[:300]
    return f"{provider_label} returned HTTP {response.status_code}: {detail}"
