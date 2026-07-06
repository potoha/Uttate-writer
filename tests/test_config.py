import json

import pytest

from uttate.config import (
    AppSettings,
    DatasetCaptureSettings,
    ProviderSettings,
    load_settings,
    save_settings,
)


def test_missing_settings_uses_local_ai_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTTATE_PROVIDER", raising=False)
    settings = load_settings(tmp_path / "missing.json", env_path=tmp_path / ".env")

    assert settings == AppSettings()
    assert settings.provider.type == "local_ai"
    assert settings.provider.model == ""
    assert settings.provider.gemini_model == "gemini-2.5-flash-lite"
    assert settings.dataset.capture_enabled is False


def test_env_file_overrides_provider_and_loads_dummy_gemini_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTTATE_PROVIDER", raising=False)
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"provider": {"type": "local_ai"}}), encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text(
        "UTTATE_PROVIDER=gemini\nGEMINI_API_KEY=dummy-1234567890\n",
        encoding="utf-8",
    )

    settings = load_settings(settings_path, env_path=env_path)

    assert settings.provider.type == "gemini"
    assert settings.provider.model == "gemini-2.5-flash-lite"
    assert settings.provider.gemini_api_key == "dummy-1234567890"


def test_env_file_loads_local_ai_lmstudio_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTTATE_PROVIDER", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "UTTATE_PROVIDER=local_ai",
                "LMSTUDIO_BASE_URL=http://localhost:1234/v1",
                "LMSTUDIO_API_KEY=local-key",
                "LMSTUDIO_MODEL=loaded-model",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path / "missing.json", env_path=env_path)

    assert settings.provider.type == "local_ai"
    assert settings.provider.compatible_base_url == "http://localhost:1234/v1"
    assert settings.provider.compatible_api_key == "local-key"
    assert settings.provider.compatible_model == "loaded-model"


def test_env_file_maps_legacy_lmstudio_to_local_ai_settings(tmp_path, monkeypatch) -> None:
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

    assert settings.provider.type == "local_ai"
    assert settings.provider.compatible_base_url == "http://localhost:1234/v1"
    assert settings.provider.compatible_api_key == "local-key"
    assert settings.provider.compatible_model == "loaded-model"


def test_env_file_maps_removed_mock_provider_to_local_ai(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTTATE_PROVIDER", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("UTTATE_PROVIDER=mock\n", encoding="utf-8")

    settings = load_settings(tmp_path / "missing.json", env_path=env_path)

    assert settings.provider.type == "local_ai"


def test_settings_file_maps_removed_mock_provider_to_local_ai(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("UTTATE_PROVIDER", raising=False)
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"provider": {"type": "mock"}}), encoding="utf-8")

    settings = load_settings(settings_path, env_path=tmp_path / ".env")

    assert settings.provider.type == "local_ai"


def test_settings_round_trip(tmp_path) -> None:
    settings_path = tmp_path / "nested" / "settings.json"
    expected = AppSettings(
        provider=ProviderSettings(
            type="openai",
            model="gpt-test",
            gemini_api_key="secret-gemini",
            openai_api_key="secret-openai",
        ),
        dataset=DatasetCaptureSettings(
            capture_enabled=True,
            capture_store_path=str(tmp_path / "candidates.jsonl"),
        ),
    )

    written_path = save_settings(expected, settings_path)

    assert written_path == settings_path
    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "gemini_api_key" not in raw["provider"]
    assert "openai_api_key" not in raw["provider"]
    loaded = load_settings(settings_path, env_path=tmp_path / ".env")
    assert loaded.provider.type == "openai"
    assert loaded.dataset.capture_enabled is True
    assert loaded.dataset.capture_store_path == str(tmp_path / "candidates.jsonl")


def test_dataset_capture_env_overrides_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UTTATE_DATASET_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("UTTATE_DATASET_CAPTURE_STORE", str(tmp_path / "env.jsonl"))
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"dataset": {"capture_enabled": False, "capture_store_path": "file.jsonl"}}),
        encoding="utf-8",
    )

    settings = load_settings(settings_path, env_path=tmp_path / ".env")

    assert settings.dataset.capture_enabled is True
    assert settings.dataset.capture_store_path == str(tmp_path / "env.jsonl")


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
