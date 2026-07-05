from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from uttate.conversion.direct import CONVERSION_SCHEMA, build_conversion_prompt, load_system_prompt
from uttate.conversion.response_parser import parse_provider_result
from uttate.models import JsonObject
from uttate.providers.base import ConversionProvider, ProviderError, ProviderResult

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
LOGGER = logging.getLogger(__name__)


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
        endpoint: str = GEMINI_API_BASE_URL,
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
        self.endpoint = endpoint.rstrip("/")
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
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        response = self._post_with_retries(headers, payload)

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
            "systemInstruction": {"parts": [{"text": self._system_prompt}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": _build_prompt(
                                "",
                                raw_text=raw_text,
                                previous_context=previous_context,
                                candidate_count=candidate_count,
                            ).strip()
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                "responseSchema": CONVERSION_SCHEMA,
            },
        }

    def _generate_content_url(self) -> str:
        model = self.model.removeprefix("models/")
        return f"{self.endpoint}/models/{model}:generateContent"

    def _post_with_retries(
        self,
        headers: dict[str, str],
        payload: JsonObject,
    ) -> httpx.Response:
        attempts = 3
        url = self._generate_content_url()
        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    return response
            except httpx.TimeoutException as error:
                message = f"Gemini timed out after {self.timeout_seconds:g} seconds."
                LOGGER.exception("Gemini timeout model=%s attempt=%s", self.model, attempt)
                raise ProviderError(message) from error
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                message = _http_error_message(error.response)
                LOGGER.warning(
                    "Gemini HTTP failure status=%s model=%s attempt=%s detail=%s",
                    status_code,
                    self.model,
                    attempt,
                    _http_error_detail(error.response),
                )
                if status_code == 503 and attempt < attempts:
                    time.sleep(float(attempt))
                    continue
                raise ProviderError(message) from error
            except httpx.RequestError as error:
                LOGGER.exception(
                    "Gemini connection failure model=%s attempt=%s",
                    self.model,
                    attempt,
                )
                raise ProviderError("Could not connect to Gemini API.") from error
        raise ProviderError("Gemini request failed after retries.")


def _build_prompt(
    system_prompt: str,
    *,
    raw_text: str,
    previous_context: str,
    candidate_count: int,
) -> str:
    return build_conversion_prompt(
        system_prompt,
        raw_text=raw_text,
        previous_context=previous_context,
        candidate_count=candidate_count,
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
    return f"Gemini API returned HTTP {response.status_code}: {_http_error_detail(response)}"


def _http_error_detail(response: httpx.Response) -> str:
    detail = response.text.strip().replace("\n", " ")[:300]
    return detail
