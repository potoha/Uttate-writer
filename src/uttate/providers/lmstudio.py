from __future__ import annotations

import threading

import httpx

from uttate.models import JsonObject
from uttate.providers.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderConnectionError,
    ProviderResponseError,
    ProviderTimeoutError,
)


class LMStudioProvider(OpenAICompatibleProvider):
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
        if self._auto_detect_model:
            with self._model_lock:
                if self._auto_detect_model:
                    self.model = self._discover_loaded_model()
                    self._auto_detect_model = False
        return super().complete_json(messages, schema)

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
