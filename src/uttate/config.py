from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Connection settings for an OpenAI-compatible provider."""

    type: str = "lmstudio"
    base_url: str = "http://localhost:1234/v1"
    api_key: str = "lm-studio"
    model: str = ""


@dataclass(frozen=True, slots=True)
class AppSettings:
    """M0 application settings with safe local defaults."""

    provider: ProviderSettings = field(default_factory=ProviderSettings)


def default_settings_path() -> Path:
    """Return the settings location, allowing tests and users to override it."""

    configured_directory = os.environ.get("UTTATE_CONFIG_DIR")
    base_directory = Path(configured_directory) if configured_directory else Path.home() / ".uttate"
    return base_directory / "settings.json"


def load_settings(path: Path | None = None) -> AppSettings:
    """Load settings from JSON, applying defaults for omitted fields."""

    settings_path = path or default_settings_path()
    if not settings_path.exists():
        return AppSettings()

    with settings_path.open(encoding="utf-8") as settings_file:
        raw_data: Any = json.load(settings_file)

    if not isinstance(raw_data, dict):
        raise ValueError("The settings file root must be a JSON object.")

    raw_provider = raw_data.get("provider", {})
    if not isinstance(raw_provider, dict):
        raise ValueError("The provider setting must be a JSON object.")

    defaults = ProviderSettings()
    provider = ProviderSettings(
        type=_string_value(raw_provider, "type", defaults.type),
        base_url=_string_value(raw_provider, "base_url", defaults.base_url),
        api_key=_string_value(raw_provider, "api_key", defaults.api_key),
        model=_string_value(raw_provider, "model", defaults.model),
    )
    return AppSettings(provider=provider)


def save_settings(settings: AppSettings, path: Path | None = None) -> Path:
    """Persist settings as human-readable UTF-8 JSON."""

    settings_path = path or default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8") as settings_file:
        json.dump(asdict(settings), settings_file, ensure_ascii=False, indent=2)
        settings_file.write("\n")
    return settings_path


def _string_value(values: dict[str, Any], key: str, default: str) -> str:
    value = values.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"The {key} setting must be a string.")
    return value
