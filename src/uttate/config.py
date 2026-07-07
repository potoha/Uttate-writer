from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Provider selection for the Project B direct-conversion branch.

    API keys intentionally come from environment variables or `.env`, not settings.json.
    This keeps local secrets out of the user-editable config file that OSS contributors
    are likely to share in issues.
    """

    type: str = "local_ai"
    model: str = ""
    timeout_seconds: float = 30.0
    previous_context_chars: int = 600
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-nano"
    openai_base_url: str = "https://api.openai.com/v1"
    compatible_base_url: str = "http://127.0.0.1:1234/v1"
    compatible_api_key: str = "lm-studio"
    compatible_model: str = ""


@dataclass(frozen=True, slots=True)
class DatasetCaptureSettings:
    """Local opt-in capture settings for review-approved training candidates."""

    capture_enabled: bool = False
    capture_store_path: str = ""


@dataclass(frozen=True, slots=True)
class ReviewHUDSettings:
    """Compact review HUD preferences."""

    visible_pending_count: int = 3
    position: str = "bottom_right"
    width: int = 420
    height: int = 320
    auto_remove_accepted: bool = True
    show_original: bool = True
    show_diff: bool = False
    always_show: bool = False


@dataclass(frozen=True, slots=True)
class InputPanelSettings:
    """Transient input panel preferences."""

    position: str = "bottom_center"
    width: int = 560
    height: int = 160


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Application settings with safe OSS defaults."""

    provider: ProviderSettings = field(default_factory=ProviderSettings)
    dataset: DatasetCaptureSettings = field(default_factory=DatasetCaptureSettings)
    review_hud: ReviewHUDSettings = field(default_factory=ReviewHUDSettings)
    input_panel: InputPanelSettings = field(default_factory=InputPanelSettings)


def default_settings_path() -> Path:
    """Return the settings location, allowing tests and users to override it."""

    configured_directory = os.environ.get("UTTATE_CONFIG_DIR")
    base_directory = Path(configured_directory) if configured_directory else Path.home() / ".uttate"
    return base_directory / "settings.json"


def default_dataset_capture_path() -> Path:
    """Return the default local candidate store used by review-mode capture."""

    return default_settings_path().parent / "dataset_candidates.jsonl"


def load_settings(path: Path | None = None, *, env_path: Path | None = None) -> AppSettings:
    """Load settings from JSON plus environment variables.

    Precedence is deliberately simple:
    defaults < settings.json < .env < real environment variables.

    The real environment wins so CI and local shells can override a checked-out `.env`
    without editing files.
    """

    settings_path = path or default_settings_path()
    file_env = _read_env_file(env_path or Path.cwd() / ".env")
    merged_env = {**file_env, **os.environ}

    if not settings_path.exists():
        return AppSettings(
            provider=_provider_from_sources({}, merged_env),
            dataset=_dataset_from_sources({}, merged_env),
        )

    with settings_path.open(encoding="utf-8") as settings_file:
        raw_data: Any = json.load(settings_file)

    if not isinstance(raw_data, dict):
        raise ValueError("The settings file root must be a JSON object.")

    raw_provider = raw_data.get("provider", {})
    if not isinstance(raw_provider, dict):
        raise ValueError("The provider setting must be a JSON object.")

    raw_dataset = raw_data.get("dataset", {})
    if not isinstance(raw_dataset, dict):
        raise ValueError("The dataset setting must be a JSON object.")

    raw_review_hud = raw_data.get("review_hud", {})
    if not isinstance(raw_review_hud, dict):
        raise ValueError("The review_hud setting must be a JSON object.")

    raw_input_panel = raw_data.get("input_panel", {})
    if not isinstance(raw_input_panel, dict):
        raise ValueError("The input_panel setting must be a JSON object.")

    return AppSettings(
        provider=_provider_from_sources(raw_provider, merged_env),
        dataset=_dataset_from_sources(raw_dataset, merged_env),
        review_hud=_review_hud_from_sources(raw_review_hud),
        input_panel=_input_panel_from_sources(raw_input_panel),
    )


def _provider_from_sources(raw_provider: dict[str, Any], env: dict[str, str]) -> ProviderSettings:
    defaults = ProviderSettings()
    provider_type = _canonical_provider_type(
        env.get("UTTATE_PROVIDER") or _string_value(raw_provider, "type", defaults.type)
    )
    return ProviderSettings(
        type=provider_type,
        model=_model_for_provider(provider_type, raw_provider, env, defaults),
        timeout_seconds=_positive_number_value(
            raw_provider,
            "timeout_seconds",
            _float_env(env, "UTTATE_TIMEOUT_SECONDS", defaults.timeout_seconds),
        ),
        previous_context_chars=_positive_int_value(
            raw_provider,
            "previous_context_chars",
            _int_env(env, "UTTATE_PREVIOUS_CONTEXT_CHARS", defaults.previous_context_chars),
        ),
        gemini_api_key=env.get("GEMINI_API_KEY", ""),
        gemini_model=env.get("GEMINI_MODEL", defaults.gemini_model),
        openai_api_key=env.get("OPENAI_API_KEY", ""),
        openai_model=env.get("OPENAI_MODEL", defaults.openai_model),
        openai_base_url=env.get("OPENAI_BASE_URL", defaults.openai_base_url),
        compatible_base_url=env.get("LMSTUDIO_BASE_URL", defaults.compatible_base_url),
        compatible_api_key=env.get("LMSTUDIO_API_KEY", defaults.compatible_api_key),
        compatible_model=env.get("LMSTUDIO_MODEL", defaults.compatible_model),
    )


def _dataset_from_sources(
    raw_dataset: dict[str, Any],
    env: dict[str, str],
) -> DatasetCaptureSettings:
    defaults = DatasetCaptureSettings()
    if env.get("UTTATE_DATASET_CAPTURE_ENABLED") not in {None, ""}:
        capture_enabled = _bool_env(
            env,
            "UTTATE_DATASET_CAPTURE_ENABLED",
            defaults.capture_enabled,
        )
    else:
        capture_enabled = _bool_value(
            raw_dataset,
            "capture_enabled",
            defaults.capture_enabled,
        )
    return DatasetCaptureSettings(
        capture_enabled=capture_enabled,
        capture_store_path=env.get(
            "UTTATE_DATASET_CAPTURE_STORE",
            _string_value(raw_dataset, "capture_store_path", defaults.capture_store_path),
        ),
    )


def _review_hud_from_sources(raw_review_hud: dict[str, Any]) -> ReviewHUDSettings:
    defaults = ReviewHUDSettings()
    visible_pending_count = _choice_int_value(
        raw_review_hud,
        "visible_pending_count",
        defaults.visible_pending_count,
        {1, 3, 5},
    )
    return ReviewHUDSettings(
        visible_pending_count=visible_pending_count,
        position=_choice_string_value(
            raw_review_hud,
            "position",
            defaults.position,
            {"bottom_right", "bottom_center", "top_right"},
        ),
        width=_positive_int_value(raw_review_hud, "width", defaults.width),
        height=_positive_int_value(raw_review_hud, "height", defaults.height),
        auto_remove_accepted=_bool_value(
            raw_review_hud,
            "auto_remove_accepted",
            defaults.auto_remove_accepted,
        ),
        show_original=_bool_value(raw_review_hud, "show_original", defaults.show_original),
        show_diff=_bool_value(raw_review_hud, "show_diff", defaults.show_diff),
        always_show=_bool_value(raw_review_hud, "always_show", defaults.always_show),
    )


def _input_panel_from_sources(raw_input_panel: dict[str, Any]) -> InputPanelSettings:
    defaults = InputPanelSettings()
    return InputPanelSettings(
        position=_choice_string_value(
            raw_input_panel,
            "position",
            defaults.position,
            {"bottom_center", "bottom_right", "top_right"},
        ),
        width=_positive_int_value(raw_input_panel, "width", defaults.width),
        height=_positive_int_value(raw_input_panel, "height", defaults.height),
    )


def save_settings(settings: AppSettings, path: Path | None = None) -> Path:
    """Persist non-secret settings as human-readable UTF-8 JSON."""

    settings_path = path or default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    provider_data = asdict(settings.provider)
    # Never write API keys into settings.json. They belong to env vars or an ignored .env file.
    provider_data.pop("gemini_api_key", None)
    provider_data.pop("openai_api_key", None)
    with settings_path.open("w", encoding="utf-8") as settings_file:
        json.dump(
            {
                "provider": provider_data,
                "dataset": asdict(settings.dataset),
                "review_hud": asdict(settings.review_hud),
                "input_panel": asdict(settings.input_panel),
            },
            settings_file,
            ensure_ascii=False,
            indent=2,
        )
        settings_file.write("\n")
    return settings_path


def _string_value(values: dict[str, Any], key: str, default: str) -> str:
    value = values.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"The {key} setting must be a string.")
    return value


def _choice_string_value(
    values: dict[str, Any],
    key: str,
    default: str,
    allowed: set[str],
) -> str:
    value = _string_value(values, key, default)
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"The {key} setting must be one of: {allowed_text}.")
    return value


def _choice_int_value(
    values: dict[str, Any],
    key: str,
    default: int,
    allowed: set[int],
) -> int:
    value = _positive_int_value(values, key, default)
    if value not in allowed:
        allowed_text = ", ".join(str(item) for item in sorted(allowed))
        raise ValueError(f"The {key} setting must be one of: {allowed_text}.")
    return value


def _positive_number_value(values: dict[str, Any], key: str, default: float) -> float:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"The {key} setting must be a positive number.")
    return float(value)


def _positive_int_value(values: dict[str, Any], key: str, default: int) -> int:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"The {key} setting must be a positive integer.")
    return value


def _bool_value(values: dict[str, Any], key: str, default: bool) -> bool:
    value = values.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"The {key} setting must be a boolean.")
    return value


def _float_env(env: dict[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except ValueError as error:
        raise ValueError(f"The {key} environment variable must be a number.") from error
    if result <= 0:
        raise ValueError(f"The {key} environment variable must be positive.")
    return result


def _int_env(env: dict[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None or value == "":
        return default
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"The {key} environment variable must be an integer.") from error
    if result <= 0:
        raise ValueError(f"The {key} environment variable must be positive.")
    return result


def _bool_env(env: dict[str, str], key: str, default: bool) -> bool:
    value = env.get(key)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"The {key} environment variable must be a boolean.")


def _canonical_provider_type(provider_type: str) -> str:
    if provider_type in {"lmstudio", "mock"}:
        return "local_ai"
    return provider_type


def _model_for_provider(
    provider_type: str,
    raw_provider: dict[str, Any],
    env: dict[str, str],
    defaults: ProviderSettings,
) -> str:
    if provider_type == "gemini":
        return env.get("GEMINI_MODEL", defaults.gemini_model)
    if provider_type == "openai":
        return env.get("OPENAI_MODEL", defaults.openai_model)
    if provider_type == "local_ai":
        return env.get("LMSTUDIO_MODEL", defaults.compatible_model)
    return _string_value(raw_provider, "model", defaults.model)


def _read_env_file(path: Path) -> dict[str, str]:
    """Read a tiny dotenv subset without adding a dependency during the cleanup step.

    Supported lines are `KEY=value`, optional quotes, and comments. That is enough for
    local API keys while keeping this first Project B cleanup dependency-neutral.
    """

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values
