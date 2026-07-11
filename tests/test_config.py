import json

import pytest

import uttate.config as config
from uttate.config import (
    AppearanceSettings,
    AppSettings,
    DatasetCaptureSettings,
    GeneralSettings,
    InputPanelSettings,
    ProviderSettings,
    ReviewHUDSettings,
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
    assert settings.dataset.collection_enabled is False
    assert settings.dataset.save_conversion_history is False
    assert settings.dataset.auto_create_candidates is False
    assert settings.dataset.require_anonymization_before_export is True
    assert settings.dataset.warn_external_api_active is True
    assert settings.dataset.allow_non_anonymized_export is False
    assert settings.general.language == "ja"
    assert settings.review_hud.visible_pending_count == 3
    assert settings.review_hud.position == "bottom_right"
    assert settings.review_hud.always_show is False
    assert settings.input_panel.position == "bottom_center"
    assert settings.input_panel.always_on_top is False
    assert settings.appearance.theme_preset == "default"
    assert settings.appearance.font_family == "sans-serif"


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
    assert settings.provider.gemini_model == "gemini-2.5-flash-lite"
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
            timeout_seconds=42.5,
            previous_context_chars=840,
            gemini_api_key="secret-gemini",
            gemini_model="gemini-test",
            openai_api_key="secret-openai",
            openai_model="openai-test",
            openai_base_url="https://openai.example.test/v1",
            compatible_base_url="http://localhost:2345/v1",
            compatible_api_key="secret-compatible",
            compatible_model="local-test",
        ),
        dataset=DatasetCaptureSettings(
            capture_enabled=True,
            collection_enabled=True,
            save_conversion_history=True,
            auto_create_candidates=True,
            warn_external_api_active=False,
            candidate_store_path=str(tmp_path / "candidates.jsonl"),
            review_store_path=str(tmp_path / "review.jsonl"),
            history_store_path=str(tmp_path / "history.jsonl"),
        ),
        general=GeneralSettings(language="en"),
        review_hud=ReviewHUDSettings(
            visible_pending_count=5,
            position="top_right",
            width=500,
            height=360,
            auto_remove_accepted=False,
            show_original=False,
            show_diff=True,
            always_show=True,
        ),
        input_panel=InputPanelSettings(
            position="bottom_right",
            width=640,
            height=180,
            always_on_top=True,
        ),
        appearance=AppearanceSettings(
            theme_preset="paper",
            custom_css_path=str(tmp_path / "user.css"),
            font_family="Arial",
            ui_font_size=15,
            review_font_size=18,
            input_font_size=19,
            queue_font_size=13,
            shortcut_font_size=12,
            debug_font_size=14,
            review_bg_image_path=str(tmp_path / "review.png"),
            review_bg_opacity=0.4,
            review_bg_blur=3,
            review_overlay=0.7,
            review_image_fit="contain",
            review_image_position="center top",
            review_panel_opacity=0.8,
            review_corner_radius=12,
        ),
    )

    written_path = save_settings(expected, settings_path)

    assert written_path == settings_path
    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "gemini_api_key" not in raw["provider"]
    assert "openai_api_key" not in raw["provider"]
    assert "compatible_api_key" not in raw["provider"]
    loaded = load_settings(settings_path, env_path=tmp_path / ".env")
    assert loaded.provider.type == "openai"
    assert loaded.provider.model == "gpt-test"
    assert loaded.provider.timeout_seconds == 42.5
    assert loaded.provider.previous_context_chars == 840
    assert loaded.provider.gemini_model == "gemini-test"
    assert loaded.provider.openai_model == "openai-test"
    assert loaded.provider.openai_base_url == "https://openai.example.test/v1"
    assert loaded.provider.compatible_base_url == "http://localhost:2345/v1"
    assert loaded.provider.compatible_model == "local-test"
    assert loaded.provider.compatible_api_key == "lm-studio"
    assert loaded.dataset.capture_enabled is True
    assert loaded.dataset.collection_enabled is True
    assert loaded.dataset.save_conversion_history is True
    assert loaded.dataset.auto_create_candidates is True
    assert loaded.dataset.warn_external_api_active is False
    assert loaded.dataset.candidate_store_path == str(tmp_path / "candidates.jsonl")
    assert loaded.dataset.review_store_path == str(tmp_path / "review.jsonl")
    assert loaded.dataset.history_store_path == str(tmp_path / "history.jsonl")
    assert loaded.dataset.capture_store_path == ""
    assert loaded.general.language == "en"
    assert loaded.review_hud.visible_pending_count == 5
    assert loaded.review_hud.position == "top_right"
    assert loaded.review_hud.auto_remove_accepted is False
    assert loaded.review_hud.show_original is False
    assert loaded.review_hud.show_diff is True
    assert loaded.review_hud.always_show is True
    assert loaded.input_panel.width == 640
    assert loaded.input_panel.always_on_top is True
    assert loaded.appearance.theme_preset == "paper"
    assert loaded.appearance.font_family == "Arial"
    assert loaded.appearance.review_bg_opacity == 0.4
    assert loaded.appearance.review_image_fit == "contain"
    assert loaded.appearance.review_corner_radius == 12


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


def test_provider_configuration_precedence_is_defaults_json_env_file_then_process(
    tmp_path, monkeypatch
) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "provider": {
                    "type": "local_ai",
                    "model": "json-model",
                    "timeout_seconds": 11,
                    "previous_context_chars": 111,
                    "gemini_model": "json-gemini",
                    "openai_model": "json-openai",
                    "openai_base_url": "https://json.example.test/v1",
                    "compatible_base_url": "http://json.example.test/v1",
                    "compatible_model": "json-local",
                    "compatible_api_key": "legacy-secret-must-be-ignored",
                }
            }
        ),
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "UTTATE_PROVIDER=gemini",
                "UTTATE_TIMEOUT_SECONDS=22",
                "UTTATE_PREVIOUS_CONTEXT_CHARS=222",
                "GEMINI_MODEL=file-gemini",
                "OPENAI_MODEL=file-openai",
                "OPENAI_BASE_URL=https://file.example.test/v1",
                "LMSTUDIO_MODEL=file-local",
                "GEMINI_API_KEY=file-gemini-key",
                "LMSTUDIO_API_KEY=file-compatible-key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("UTTATE_PROVIDER", "openai")
    monkeypatch.setenv("UTTATE_TIMEOUT_SECONDS", "33")
    monkeypatch.setenv("OPENAI_MODEL", "process-openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://process.example.test/v1")
    monkeypatch.setenv("GEMINI_API_KEY", "process-gemini-key")

    settings = load_settings(settings_path, env_path=env_path)

    assert settings.provider.type == "openai"
    assert settings.provider.model == "json-model"
    assert settings.provider.timeout_seconds == 33
    assert settings.provider.previous_context_chars == 222
    assert settings.provider.gemini_model == "file-gemini"
    assert settings.provider.openai_model == "process-openai"
    assert settings.provider.openai_base_url == "https://process.example.test/v1"
    assert settings.provider.compatible_base_url == "http://json.example.test/v1"
    assert settings.provider.compatible_model == "file-local"
    assert settings.provider.gemini_api_key == "process-gemini-key"
    assert settings.provider.compatible_api_key == "file-compatible-key"


def test_save_settings_preserves_existing_file_when_atomic_replace_fails(
    tmp_path, monkeypatch
) -> None:
    settings_path = tmp_path / "settings.json"
    original_content = '{"existing": true}\n'
    settings_path.write_text(original_content, encoding="utf-8")

    def fail_replace(source, destination) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(config.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        save_settings(AppSettings(), settings_path)

    assert settings_path.read_text(encoding="utf-8") == original_content
    assert list(tmp_path.glob(".settings.json.*.tmp")) == []
