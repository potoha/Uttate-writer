import json

import httpx

from uttate.providers.local_ai import LocalAIProvider


def test_local_ai_provider_runs_stage_1_normalizer_with_lmstudio_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "loaded-local"}]})
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][-1]["content"])
        assert payload["model"] == "loaded-local"
        assert payload["response_format"]["json_schema"]["schema"]["required"] == [
            "source_echo",
            "normalized",
            "segments",
            "uncertain",
        ]
        assert user_payload["original_raw"] == "keyboardhabunbougu"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "source_echo": "keyboardhabunbougu",
                                    "normalized": "keyboard は ぶんぼうぐ",
                                    "segments": [
                                        {
                                            "raw": "keyboard",
                                            "reading": "keyboard",
                                            "type": "english",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": "ha",
                                            "reading": "は",
                                            "type": "particle",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": "bunbougu",
                                            "reading": "ぶんぼうぐ",
                                            "type": "noun",
                                            "confidence": 1.0,
                                        },
                                    ],
                                    "uncertain": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    provider = LocalAIProvider(
        base_url="http://local.test/v1",
        api_key="local-key",
        model="",
        transport=httpx.MockTransport(handler),
    )

    result = provider.convert("keyboardhabunbougu")

    assert result.provider == "local_ai"
    assert result.model == "loaded-local"
    assert result.candidates[0].label == "faithful_reading"
    assert result.candidates[0].text == "keyboard は ぶんぼうぐ"
    assert [request.url.path for request in requests] == ["/v1/models", "/v1/chat/completions"]
