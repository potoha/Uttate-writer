import json

import pytest

from uttate.config import AppSettings, ProviderSettings, load_settings, save_settings


def test_missing_settings_uses_mock_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTTATE_PROVIDER", raising=False)
    settings = load_settings(tmp_path / "missing.json", env_path=tmp_path / ".env")

    assert settings == AppSettings()
    assert settings.provider.type == "mock"
    assert settings.provider.model == ""
    assert settings.provider.gemini_model == "gemini-2.5-flash-lite"


def test_env_file_overrides_provider_and_loads_dummy_gemini_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTTATE_PROVIDER", raising=False)
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"provider": {"type": "mock"}}), encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text(
        "UTTATE_PROVIDER=gemini\nGEMINI_API_KEY=dummy-1234567890\n",
        encoding="utf-8",
    )

    settings = load_settings(settings_path, env_path=env_path)

    assert settings.provider.type == "gemini"
    assert settings.provider.model == "gemini-2.5-flash-lite"
    assert settings.provider.gemini_api_key == "dummy-1234567890"


def test_env_file_loads_lmstudio_compatible_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTTATE_PROVIDER", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "UTTATE_PROVIDER=lmstudio",
                "LMSTUDIO_BASE_URL=http://localhost:1234/v1",
                "LMSTUDIO_API_KEY=local-key",
                "LMSTUDIO_MODEL=loaded-model",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path / "missing.json", env_path=env_path)

    assert settings.provider.type == "lmstudio"
    assert settings.provider.compatible_base_url == "http://localhost:1234/v1"
    assert settings.provider.compatible_api_key == "local-key"
    assert settings.provider.compatible_model == "loaded-model"


def test_settings_round_trip(tmp_path) -> None:
    settings_path = tmp_path / "nested" / "settings.json"
    expected = AppSettings(
        provider=ProviderSettings(
            type="openai",
            model="gpt-test",
            gemini_api_key="secret-gemini",
            openai_api_key="secret-openai",
        )
    )

    written_path = save_settings(expected, settings_path)

    assert written_path == settings_path
    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "gemini_api_key" not in raw["provider"]
    assert "openai_api_key" not in raw["provider"]
    assert load_settings(settings_path, env_path=tmp_path / ".env").provider.type == "openai"


def test_non_object_settings_are_rejected(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="root must be a JSON object"):
        load_settings(settings_path)


def test_non_positive_provider_timeout_is_rejected(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"provider": {"timeout_seconds": 0}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="positive number"):
        load_settings(settings_path, env_path=tmp_path / ".env")
