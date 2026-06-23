import json

import pytest

from uttate.config import AppSettings, ProviderSettings, load_settings, save_settings


def test_missing_settings_uses_local_lm_studio_defaults(tmp_path) -> None:
    settings = load_settings(tmp_path / "missing.json")

    assert settings == AppSettings()
    assert settings.provider.base_url == "http://localhost:1234/v1"
    assert settings.provider.model == ""


def test_partial_provider_settings_preserve_other_defaults(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"provider": {"model": "local-model"}}),
        encoding="utf-8",
    )

    settings = load_settings(settings_path)

    assert settings.provider.model == "local-model"
    assert settings.provider.type == "lmstudio"
    assert settings.provider.api_key == "lm-studio"


def test_settings_round_trip(tmp_path) -> None:
    settings_path = tmp_path / "nested" / "settings.json"
    expected = AppSettings(
        provider=ProviderSettings(
            type="openai_compatible",
            base_url="http://example.test/v1",
            api_key="test-key",
            model="test-model",
        )
    )

    written_path = save_settings(expected, settings_path)

    assert written_path == settings_path
    assert load_settings(settings_path) == expected


def test_non_object_settings_are_rejected(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="root must be a JSON object"):
        load_settings(settings_path)
