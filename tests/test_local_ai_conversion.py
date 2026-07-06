import json

import httpx

from uttate.conversion.local_ai import ReadingNormalizer
from uttate.models import JsonObject
from uttate.prompts.registry import LocalAIPromptProfile, LocalAIPromptRegistry
from uttate.providers.local_ai import LocalAIProvider


class RecordingProvider:
    def __init__(self, response: JsonObject | Exception) -> None:
        self.response = response
        self.messages: list[list[JsonObject]] = []

    def complete_json(
        self,
        messages: list[JsonObject],
        schema: JsonObject | None = None,
    ) -> JsonObject:
        del schema
        self.messages.append(messages)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _registry(tmp_path, *, default_prompt: str = "default prompt") -> LocalAIPromptRegistry:
    return LocalAIPromptRegistry(
        tmp_path / "local_ai_prompts.yaml",
        {
            "default": LocalAIPromptProfile(
                name="default",
                model="",
                prompt=default_prompt,
                default_prompt_snapshot=default_prompt,
            ),
            "model_loaded-local": LocalAIPromptProfile(
                name="model_loaded-local",
                model="loaded-local",
                prompt="loaded-local prompt",
                default_prompt_snapshot=default_prompt,
            ),
        },
        default_prompt=default_prompt,
    )


def test_local_ai_provider_runs_stage2_with_lmstudio_payload(tmp_path) -> None:
    requests: list[httpx.Request] = []
    registry = _registry(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "loaded-local"}]})
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][-1]["content"])
        assert payload["model"] == "loaded-local"
        assert payload["response_format"]["json_schema"]["schema"]["required"] == [
            "candidates",
            "uncertain",
        ]
        assert user_payload["task"] == "aggressive_kanji_conversion_from_normalized_reading"
        assert user_payload["conversion_stage"] == "stage2_kanji_conversion"
        assert user_payload["input_text"] == "keyboard は ぶんぼうぐ"
        assert user_payload["normalized_input"] == "keyboard は ぶんぼうぐ"
        assert user_payload["kanji_conversion_policy"]["avoid_unnecessary_hiragana"] is True
        assert "keyboardhabunbougu" not in payload["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "candidates": [
                                        {
                                            "label": "faithful",
                                            "text": "keyboardは文房具",
                                        },
                                        {
                                            "label": "natural",
                                            "text": "keyboardは文房具です",
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
    assert result.candidates[0].label == "faithful"
    assert result.candidates[0].text == "keyboardは文房具"
    assert [request.url.path for request in requests] == ["/v1/models", "/v1/chat/completions"]


def test_local_ai_provider_masks_protected_tags_and_restores_stage2_result(tmp_path) -> None:
    registry = _registry(tmp_path)
    masked_source = "__UTTATE_PROTECTED_0__ は __UTTATE_PROTECTED_1__ に __UTTATE_PROTECTED_2__"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "loaded-local"}]})
        payload = json.loads(request.content)
        user_payload = json.loads(payload["messages"][-1]["content"])
        serialized_payload = payload["messages"][-1]["content"]
        assert "dedodamu" not in serialized_payload
        assert "English" not in serialized_payload
        assert "tokiori" not in serialized_payload
        assert user_payload["normalized_input"] == masked_source
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
                                    "candidates": [
                                        {
                                            "label": "faithful",
                                            "text": (
                                                "__UTTATE_PROTECTED_0__は"
                                                "__UTTATE_PROTECTED_1__に"
                                                "__UTTATE_PROTECTED_2__"
                                            ),
                                        }
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

    result = provider.convert("\\dedodamu\\ ha =English= ni $tokiori$")

    assert result.candidates[0].text == "デドダムはEnglishにときおり"


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
                                    "candidates": [
                                        {"label": "faithful", "text": "は"},
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


def test_stage2_uses_mechanical_normalized_input() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {"label": "faithful", "text": "日本語"},
                {"label": "natural", "text": "日本語です"},
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    normalizer.convert_to_provider_result("nihonngo")

    payload = json.loads(provider.messages[0][-1]["content"])
    assert payload["task"] == "aggressive_kanji_conversion_from_normalized_reading"
    assert payload["input_text"] == "にほんご"
    assert payload["normalized_input"] == "にほんご"


def test_stage2_failure_falls_back_to_mechanical_normalized() -> None:
    normalizer = ReadingNormalizer(
        RecordingProvider({"candidates": [], "uncertain": []}),
        enable_ambiguity_resolver=False,
    )

    result = normalizer.convert_to_provider_result("nihonngo")

    assert result.candidates[0].label == "mechanical_normalized"
    assert result.candidates[0].text == "にほんご"


def test_local_ai_does_not_error_on_fidelity_failure_path() -> None:
    normalizer = ReadingNormalizer(
        RecordingProvider(RuntimeError("old reading path exploded")),
        enable_ambiguity_resolver=False,
    )

    result = normalizer.convert_to_provider_result("koreha")

    assert result.candidates[0].text == "これは"


def test_local_ai_calls_stage2_after_mechanical_normalization() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {
                    "label": "faithful",
                    "text": (
                        "日本語変換__UTTATE_PROTECTED_0__、これは便利な"
                        "__UTTATE_PROTECTED_1__だね。"
                    ),
                }
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    normalizer.convert_to_provider_result(
        "nihonngo | henkan | =tool= | koreha | bennrina | \\siromono\\ | dane."
    )

    payload = json.loads(provider.messages[0][-1]["content"])
    assert payload["input_text"] == (
        "にほんご | へんかん | __UTTATE_PROTECTED_0__ | これは | べんりな | "
        "__UTTATE_PROTECTED_1__ | だね."
    )


def test_local_ai_prefers_stage2_candidates_over_mechanical_fallback() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {"label": "faithful", "text": "日本語変換tool、これは便利なシロモノだね。"},
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result("nihonngo | henkan | koreha")

    assert result.candidates[0].label == "faithful"
    assert result.candidates[0].text == "日本語変換tool、これは便利なシロモノだね。"


def test_local_ai_stage2_failure_falls_back_to_mechanical_normalized() -> None:
    provider = RecordingProvider({"candidates": [], "uncertain": []})
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result("nihonngo | henkan")

    assert result.candidates[0].label == "mechanical_normalized"
    assert result.candidates[0].text == "にほんご | へんかん"


def test_local_ai_stage2_preserves_and_restores_placeholders() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {
                    "label": "faithful",
                    "text": "日本語変換__UTTATE_PROTECTED_0__、便利な__UTTATE_PROTECTED_1__。",
                }
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result("nihonngo | henkan | =tool= | \\siromono\\")

    assert result.candidates[0].text == "日本語変換tool、便利なシロモノ。"


def test_local_ai_stage2_does_not_receive_raw_rough_input() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {
                    "label": "faithful",
                    "text": (
                        "日本語変換__UTTATE_PROTECTED_0__、これは便利な"
                        "__UTTATE_PROTECTED_1__だね。"
                    ),
                }
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    normalizer.convert_to_provider_result(
        "nihonngo | henkan | =tool= | koreha | bennrina | \\siromono\\ | dane."
    )

    payload_text = provider.messages[0][-1]["content"]
    assert "nihonngo" not in payload_text
    assert "bennrina" not in payload_text
    assert "にほんご" in payload_text
    assert "べんりな" in payload_text


def test_stage2_converts_common_nouns_to_kanji() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {"label": "faithful", "text": "今日はlocal AIの変換精度を確かめる。"},
                {"label": "natural", "text": "今日はlocal AIの変換精度を確かめる。"},
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result(
        "きょうは | local AI の | へんかんせいどを | たしかめる"
    )

    assert result.candidates[0].text == "今日はlocal AIの変換精度を確かめる。"
    assert "きょう" not in result.candidates[0].text
    assert "へんかんせいど" not in result.candidates[0].text
    assert "たしかめる" not in result.candidates[0].text


def test_stage2_converts_verb_and_adjective_stems() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {"label": "faithful", "text": "このtoolは入力のstressを減らす。"},
                {"label": "natural", "text": "このtoolは入力のstressを減らす。"},
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result(
        "この | tool は | にゅうりょくの | stress を | へらす"
    )

    assert result.candidates[0].text == "このtoolは入力のstressを減らす。"


def test_stage2_avoids_unnecessary_hiragana() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {"label": "faithful", "text": "変換結果をUIに表示する。"},
                {"label": "natural", "text": "変換結果をUIに表示する。"},
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result("へんかんけっかを | UI に | ひょうじする")

    assert result.candidates[0].text == "変換結果をUIに表示する。"
    assert "へんかんけっか" not in result.candidates[0].text
    assert "ひょうじ" not in result.candidates[0].text


def test_stage2_preserves_placeholders_while_converting_surrounding_japanese() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {
                    "label": "faithful",
                    "text": (
                        "日本語変換__UTTATE_PROTECTED_0__、これは便利な"
                        "__UTTATE_PROTECTED_1__だね。"
                    ),
                },
                {
                    "label": "natural",
                    "text": (
                        "日本語変換__UTTATE_PROTECTED_0__、これは便利な"
                        "__UTTATE_PROTECTED_1__だね。"
                    ),
                },
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result(
        "にほんご | へんかん | =tool= | これは | べんりな | \\siromono\\ | だね."
    )

    assert result.candidates[0].text == "日本語変換tool、これは便利なシロモノだね。"


def test_stage2_does_not_add_meaning_while_converting_kanji() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {"label": "faithful", "text": "今の仕様だとユーザーの入力をそのまま扱える。"},
                {"label": "natural", "text": "今の仕様だとユーザーの入力をそのまま扱える。"},
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result(
        "いまの | しようだと | ゆーざーの | にゅうりょくを | そのまま | あつかえる"
    )

    assert result.candidates[0].text == "今の仕様だとユーザーの入力をそのまま扱える。"
    assert "内容" not in result.candidates[0].text
    assert "安全" not in result.candidates[0].text


def test_stage2_keeps_casual_style() -> None:
    provider = RecordingProvider(
        {
            "candidates": [
                {"label": "faithful", "text": "これは便利だね。"},
                {"label": "natural", "text": "これは便利だね。"},
            ],
            "uncertain": [],
        }
    )
    normalizer = ReadingNormalizer(provider, enable_ambiguity_resolver=False)

    result = normalizer.convert_to_provider_result("これは | べんりだね")

    assert result.candidates[0].text == "これは便利だね。"
    assert "です" not in result.candidates[0].text
