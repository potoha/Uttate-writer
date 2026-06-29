from __future__ import annotations

from importlib import resources
from typing import Any

import httpx

from uttate.models import JsonObject
from uttate.pipeline.response_parser import parse_provider_result
from uttate.providers.base import ConversionProvider, ProviderError, ProviderResult

GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

_GEMINI_SCHEMA: JsonObject = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["label", "text"],
            },
        },
        "uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string"},
                    "candidates": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["raw", "candidates", "reason"],
            },
        },
    },
    "required": ["candidates", "uncertain"],
}


class GeminiProvider(ConversionProvider):
    """Gemini REST provider for Project B direct conversion.

    The implementation uses `httpx`, already present in the project, instead of adding a
    new SDK dependency during the MVP path. That keeps repo-local setup predictable while
    still using Google's structured JSON response contract.
    """

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        endpoint: str = GEMINI_INTERACTIONS_URL,
    ) -> None:
        if not api_key.strip():
            raise ProviderError("GEMINI_API_KEY is not set.")
        if not model.strip():
            raise ProviderError("GEMINI_MODEL is not set.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")

        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.endpoint = endpoint
        self._transport = transport
        self._system_prompt = _load_system_prompt()

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
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.post(self.endpoint, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            message = f"Gemini timed out after {self.timeout_seconds:g} seconds."
            raise ProviderError(message) from error
        except httpx.HTTPStatusError as error:
            raise ProviderError(_http_error_message(error.response)) from error
        except httpx.RequestError as error:
            raise ProviderError("Could not connect to Gemini API.") from error

        response_data = _response_json(response)
        output_text = _output_text(response_data)
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
            "input": _build_prompt(
                self._system_prompt,
                raw_text=raw_text,
                previous_context=previous_context,
                candidate_count=candidate_count,
            ),
            "temperature": 0.2,
            "max_output_tokens": 1024,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": _GEMINI_SCHEMA,
            },
        }


def _load_system_prompt() -> str:
    return (
        resources.files("uttate.prompts")
        .joinpath("api_direct_converter_system.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def _build_prompt(
    system_prompt: str,
    *,
    raw_text: str,
    previous_context: str,
    candidate_count: int,
) -> str:
    context = previous_context.strip() or "(なし)"
    return (
        f"{system_prompt}\n\n"
        f"候補数: {candidate_count}\n\n"
        f"直前の文脈:\n{context}\n\n"
        f"入力:\n{raw_text.strip()}\n"
    )


def _response_json(response: httpx.Response) -> JsonObject:
    try:
        decoded: Any = response.json()
    except ValueError as error:
        raise ProviderError("Gemini response was not valid JSON.") from error
    if not isinstance(decoded, dict):
        raise ProviderError("Gemini response root must be an object.")
    return decoded


def _output_text(response_data: JsonObject) -> str:
    output_text = response_data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    # Fallback for generateContent-like payloads. This keeps the provider resilient if a
    # user proxies Gemini through a compatible endpoint with the older response shape.
    try:
        parts = response_data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as error:
        raise ProviderError("Gemini response did not include output_text.") from error
    if not isinstance(parts, list):
        raise ProviderError("Gemini response parts must be an array.")
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text.strip():
        raise ProviderError("Gemini response text was empty.")
    return text


def _http_error_message(response: httpx.Response) -> str:
    detail = response.text.strip().replace("\n", " ")[:300]
    # Do not include request headers or URLs with secrets. The API key is sent only in a
    # header, so the user-visible message can safely mention status and body detail.
    return f"Gemini API returned HTTP {response.status_code}: {detail}"
