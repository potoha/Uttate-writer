import json

import httpx

from uttate.prompts.registry import LocalAIPromptProfile, LocalAIPromptRegistry
from uttate.providers.local_ai import LocalAIProvider


def test_local_ai_provider_runs_stage_1_normalizer_with_lmstudio_payload(tmp_path) -> None:
    requests: list[httpx.Request] = []
    registry = LocalAIPromptRegistry(
        tmp_path / "local_ai_prompts.yaml",
        {
            "default": LocalAIPromptProfile(
                name="default",
                model="",
                prompt="default prompt",
                default_prompt_snapshot="default prompt",
            ),
            "model_loaded-local": LocalAIPromptProfile(
                name="model_loaded-local",
                model="loaded-local",
                prompt="loaded-local prompt",
                default_prompt_snapshot="default prompt",
            ),
        },
        default_prompt="default prompt",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "loaded-local"}]})
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][-1]["content"])
        assert payload["model"] == "loaded-local"
        assert payload["messages"][0]["content"] == "loaded-local prompt"
        assert payload["response_format"]["json_schema"]["schema"]["required"] == [
            "source_echo",
            "normalized",
            "segments",
            "uncertain",
        ]
        assert user_payload["original_raw"] == "keyboardhabunbougu"
        assert user_payload["original_raw_masked"] == "keyboardhabunbougu"
        assert user_payload["protected_placeholders"] == []
        assert user_payload["preprocessed_segments"][0]["raw_masked"] == "keyboardhabunbougu"
        assert "mechanical_strict" in user_payload["preprocessed_segments"][0]
        assert "mechanical_typo_tolerant" in user_payload["preprocessed_segments"][0]
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
        prompt_registry=registry,
    )

    result = provider.convert("keyboardhabunbougu")

    assert result.provider == "local_ai"
    assert result.model == "loaded-local"
    assert result.candidates[0].label == "faithful_reading"
    assert result.candidates[0].text == "keyboard は ぶんぼうぐ"
    assert [request.url.path for request in requests] == ["/v1/models", "/v1/chat/completions"]


def test_local_ai_provider_masks_protected_tags_and_restores_after_validation(tmp_path) -> None:
    registry = LocalAIPromptRegistry(
        tmp_path / "local_ai_prompts.yaml",
        {
            "default": LocalAIPromptProfile(
                name="default",
                model="",
                prompt="default prompt",
                default_prompt_snapshot="default prompt",
            ),
            "model_loaded-local": LocalAIPromptProfile(
                name="model_loaded-local",
                model="loaded-local",
                prompt="loaded-local prompt",
                default_prompt_snapshot="default prompt",
            ),
        },
        default_prompt="default prompt",
    )
    masked_source = "__UTTATE_PROTECTED_0__ ha __UTTATE_PROTECTED_1__ to __UTTATE_PROTECTED_2__"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "loaded-local"}]})
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][-1]["content"])
        serialized_payload = payload["messages"][-1]["content"]
        assert "dedodamu" not in serialized_payload
        assert "English" not in serialized_payload
        assert "tokiori" not in serialized_payload
        assert user_payload["original_raw"] == masked_source
        assert user_payload["original_raw_masked"] == masked_source
        assert user_payload["protected_placeholders"] == [
            {
                "placeholder": "__UTTATE_PROTECTED_0__",
                "kind": "katakana_name",
                "instruction": (
                    "Copy this placeholder exactly. It will be restored after validation."
                ),
            },
            {
                "placeholder": "__UTTATE_PROTECTED_1__",
                "kind": "preserve_english",
                "instruction": (
                    "Copy this placeholder exactly. It will be restored after validation."
                ),
            },
            {
                "placeholder": "__UTTATE_PROTECTED_2__",
                "kind": "hiragana",
                "instruction": (
                    "Copy this placeholder exactly. It will be restored after validation."
                ),
            },
        ]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "source_echo": masked_source,
                                    "normalized": (
                                        "__UTTATE_PROTECTED_0__ は "
                                        "__UTTATE_PROTECTED_1__ と "
                                        "__UTTATE_PROTECTED_2__"
                                    ),
                                    "segments": [
                                        {
                                            "raw": "__UTTATE_PROTECTED_0__",
                                            "reading": "__UTTATE_PROTECTED_0__",
                                            "type": "unknown",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": " ",
                                            "reading": " ",
                                            "type": "symbol",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": "ha",
                                            "reading": "は",
                                            "type": "particle",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": " ",
                                            "reading": " ",
                                            "type": "symbol",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": "__UTTATE_PROTECTED_1__",
                                            "reading": "__UTTATE_PROTECTED_1__",
                                            "type": "unknown",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": " ",
                                            "reading": " ",
                                            "type": "symbol",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": "to",
                                            "reading": "と",
                                            "type": "particle",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": " ",
                                            "reading": " ",
                                            "type": "symbol",
                                            "confidence": 1.0,
                                        },
                                        {
                                            "raw": "__UTTATE_PROTECTED_2__",
                                            "reading": "__UTTATE_PROTECTED_2__",
                                            "type": "unknown",
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
        prompt_registry=registry,
    )

    result = provider.convert("\\dedodamu\\ ha =English= to $tokiori$")

    assert result.candidates[0].text == "デドダム は English と ときおり"


def test_local_ai_provider_auto_creates_profile_for_detected_model(tmp_path) -> None:
    registry = LocalAIPromptRegistry(
        tmp_path / "local_ai_prompts.yaml",
        {
            "default": LocalAIPromptProfile(
                name="default",
                model="",
                prompt="default prompt",
                default_prompt_snapshot="default prompt",
            )
        },
        default_prompt="default prompt",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "new-local-model"}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "source_echo": "ha",
                                    "normalized": "は",
                                    "segments": [
                                        {
                                            "raw": "ha",
                                            "reading": "は",
                                            "type": "particle",
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
        model="",
        transport=httpx.MockTransport(handler),
        prompt_registry=registry,
    )

    provider.convert("ha")

    assert registry.profile("model_new-local-model").model == "new-local-model"
    assert registry.profile("model_new-local-model").prompt == "default prompt"
    assert "new-local-model" in registry.path.read_text(encoding="utf-8")
