from __future__ import annotations

import json

import httpx
import pytest

from uttate.providers.lmstudio import LMStudioProvider
from uttate.providers.openai_compatible import ProviderResponseError


def test_lmstudio_auto_detects_the_loaded_model_once() -> None:
    model_requests = 0
    completion_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal model_requests
        if request.url.path == "/v1/models":
            model_requests += 1
            return httpx.Response(200, json={"data": [{"id": "loaded-model"}]})
        payload = json.loads(request.content)
        completion_models.append(payload["model"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    provider = LMStudioProvider(transport=httpx.MockTransport(handler))

    provider.complete_json([{"role": "user", "content": "one"}])
    provider.complete_json([{"role": "user", "content": "two"}])

    assert model_requests == 1
    assert completion_models == ["loaded-model", "loaded-model"]


def test_lmstudio_reports_when_no_model_is_loaded() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))

    with pytest.raises(ProviderResponseError, match="no loaded model"):
        LMStudioProvider(transport=transport).complete_json([{"role": "user", "content": "x"}])
