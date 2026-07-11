from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


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
    collection_enabled: bool = False
    save_conversion_history: bool = False
    auto_create_candidates: bool = False
    warn_external_api_active: bool = True
    # Deprecated compatibility-only values. They are neither displayed nor persisted.
    require_anonymization_before_export: bool = True
    allow_non_anonymized_export: bool = False
    candidate_store_path: str = ""
    review_store_path: str = ""
    history_store_path: str = ""
    # Read-only migration source for settings created before store paths were split.
    capture_store_path: str = ""


@dataclass(frozen=True, slots=True)
class GeneralSettings:
    """General UI preferences."""

    language: str = "ja"


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
    always_on_top: bool = False


@dataclass(frozen=True, slots=True)
class AppearanceSettings:
    """CSS-like appearance settings for independent UI windows."""

    theme_preset: str = "default"
    custom_css_path: str = ""
    font_family: str = "sans-serif"
    ui_font_size: int = 13
    review_font_size: int = 13
    input_font_size: int = 14
    queue_font_size: int = 12
    shortcut_font_size: int = 11
    debug_font_size: int = 12
    preview_text: str = "Uttate Writer"
    review_bg_image_path: str = ""
    review_bg_opacity: float = 0.0
    review_bg_blur: int = 0
    review_overlay: float = 0.86
    review_image_fit: str = "cover"
    review_image_position: str = "center"
    review_panel_opacity: float = 0.96
    review_corner_radius: int = 8
    input_bg_image_path: str = ""
    input_bg_opacity: float = 0.0
    input_bg_blur: int = 0
    input_overlay: float = 0.88
    input_image_fit: str = "cover"
    input_image_position: str = "center"
    input_panel_opacity: float = 0.96
    input_corner_radius: int = 8
    debug_bg_image_path: str = ""
    debug_bg_opacity: float = 0.0
    debug_bg_blur: int = 0
    debug_overlay: float = 0.92
    debug_panel_opacity: float = 0.98


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Application settings with safe OSS defaults."""

    provider: ProviderSettings = field(default_factory=ProviderSettings)
    dataset: DatasetCaptureSettings = field(default_factory=DatasetCaptureSettings)
    general: GeneralSettings = field(default_factory=GeneralSettings)
    review_hud: ReviewHUDSettings = field(default_factory=ReviewHUDSettings)
    input_panel: InputPanelSettings = field(default_factory=InputPanelSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)


def default_settings_path() -> Path:
    """Return the settings location, allowing tests and users to override it."""

    configured_directory = os.environ.get("UTTATE_CONFIG_DIR")
    base_directory = Path(configured_directory) if configured_directory else Path.home() / ".uttate"
    return base_directory / "settings.json"


def default_dataset_capture_path() -> Path:
    """Return the default local candidate store used by review-mode capture."""

    return default_settings_path().parent / "dataset_candidates.jsonl"


def default_dataset_history_path() -> Path:
    """Return the default local review store for Dataset Collection Mode."""

    return default_settings_path().parent / "dataset_review.jsonl"


def default_conversion_history_path() -> Path:
    """Return the opt-in conversion history store, separate from review candidates."""

    return default_settings_path().parent / "conversion_history.jsonl"


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

    raw_general = raw_data.get("general", {})
    if not isinstance(raw_general, dict):
        raise ValueError("The general setting must be a JSON object.")

    raw_review_hud = raw_data.get("review_hud", {})
    if not isinstance(raw_review_hud, dict):
        raise ValueError("The review_hud setting must be a JSON object.")

    raw_input_panel = raw_data.get("input_panel", {})
    if not isinstance(raw_input_panel, dict):
        raise ValueError("The input_panel setting must be a JSON object.")

    raw_appearance = raw_data.get("appearance", {})
    if not isinstance(raw_appearance, dict):
        raise ValueError("The appearance setting must be a JSON object.")

    return AppSettings(
        provider=_provider_from_sources(raw_provider, merged_env),
        dataset=_dataset_from_sources(raw_dataset, merged_env),
        general=_general_from_sources(raw_general),
        review_hud=_review_hud_from_sources(raw_review_hud),
        input_panel=_input_panel_from_sources(raw_input_panel),
        appearance=_appearance_from_sources(raw_appearance),
    )


def _provider_from_sources(raw_provider: dict[str, Any], env: dict[str, str]) -> ProviderSettings:
    defaults = ProviderSettings()
    provider_type = _canonical_provider_type(
        _env_or_string_value(env, "UTTATE_PROVIDER", raw_provider, "type", defaults.type)
    )
    return ProviderSettings(
        type=provider_type,
        model=_string_value(raw_provider, "model", defaults.model),
        timeout_seconds=_number_from_sources(
            raw_provider, env, "timeout_seconds", "UTTATE_TIMEOUT_SECONDS", defaults.timeout_seconds
        ),
        previous_context_chars=_int_from_sources(
            raw_provider,
            env,
            "previous_context_chars",
            "UTTATE_PREVIOUS_CONTEXT_CHARS",
            defaults.previous_context_chars,
        ),
        gemini_api_key=env.get("GEMINI_API_KEY", ""),
        gemini_model=_env_or_string_value(
            env, "GEMINI_MODEL", raw_provider, "gemini_model", defaults.gemini_model
        ),
        openai_api_key=env.get("OPENAI_API_KEY", ""),
        openai_model=_env_or_string_value(
            env, "OPENAI_MODEL", raw_provider, "openai_model", defaults.openai_model
        ),
        openai_base_url=_env_or_string_value(
            env, "OPENAI_BASE_URL", raw_provider, "openai_base_url", defaults.openai_base_url
        ),
        compatible_base_url=_env_or_string_value(
            env,
            "LMSTUDIO_BASE_URL",
            raw_provider,
            "compatible_base_url",
            defaults.compatible_base_url,
        ),
        compatible_api_key=env.get("LMSTUDIO_API_KEY", defaults.compatible_api_key),
        compatible_model=_env_or_string_value(
            env, "LMSTUDIO_MODEL", raw_provider, "compatible_model", defaults.compatible_model
        ),
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
    collection_enabled = _bool_value(
        raw_dataset,
        "collection_enabled",
        _bool_value(raw_dataset, "capture_enabled", defaults.collection_enabled),
    )
    return DatasetCaptureSettings(
        capture_enabled=capture_enabled,
        collection_enabled=collection_enabled,
        save_conversion_history=_bool_value(
            raw_dataset,
            "save_conversion_history",
            defaults.save_conversion_history,
        ),
        auto_create_candidates=_bool_value(
            raw_dataset,
            "auto_create_candidates",
            defaults.auto_create_candidates,
        ),
        warn_external_api_active=_bool_value(
            raw_dataset,
            "warn_external_api_active",
            defaults.warn_external_api_active,
        ),
        candidate_store_path=env.get(
            "UTTATE_DATASET_CANDIDATE_STORE",
            _string_value(raw_dataset, "candidate_store_path", defaults.candidate_store_path),
        ),
        review_store_path=env.get(
            "UTTATE_DATASET_REVIEW_STORE",
            _string_value(raw_dataset, "review_store_path", defaults.review_store_path),
        ),
        history_store_path=env.get(
            "UTTATE_CONVERSION_HISTORY_STORE",
            _string_value(raw_dataset, "history_store_path", defaults.history_store_path),
        ),
        capture_store_path=env.get(
            "UTTATE_DATASET_CAPTURE_STORE",
            _string_value(
                raw_dataset,
                "capture_store_path",
                defaults.capture_store_path,
            ),
        ),
    )


def _general_from_sources(raw_general: dict[str, Any]) -> GeneralSettings:
    defaults = GeneralSettings()
    return GeneralSettings(
        language=_choice_string_value(raw_general, "language", defaults.language, {"ja", "en"}),
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
        always_on_top=_bool_value(raw_input_panel, "always_on_top", defaults.always_on_top),
    )


def _appearance_from_sources(raw_appearance: dict[str, Any]) -> AppearanceSettings:
    defaults = AppearanceSettings()
    image_fit_values = {"cover", "contain", "tile", "stretch"}
    return AppearanceSettings(
        theme_preset=_string_value(raw_appearance, "theme_preset", defaults.theme_preset),
        custom_css_path=_string_value(raw_appearance, "custom_css_path", defaults.custom_css_path),
        font_family=_string_value(raw_appearance, "font_family", defaults.font_family),
        ui_font_size=_positive_int_value(raw_appearance, "ui_font_size", defaults.ui_font_size),
        review_font_size=_positive_int_value(
            raw_appearance, "review_font_size", defaults.review_font_size
        ),
        input_font_size=_positive_int_value(
            raw_appearance, "input_font_size", defaults.input_font_size
        ),
        queue_font_size=_positive_int_value(
            raw_appearance, "queue_font_size", defaults.queue_font_size
        ),
        shortcut_font_size=_positive_int_value(
            raw_appearance, "shortcut_font_size", defaults.shortcut_font_size
        ),
        debug_font_size=_positive_int_value(
            raw_appearance, "debug_font_size", defaults.debug_font_size
        ),
        preview_text=_string_value(raw_appearance, "preview_text", defaults.preview_text),
        review_bg_image_path=_string_value(
            raw_appearance, "review_bg_image_path", defaults.review_bg_image_path
        ),
        review_bg_opacity=_ratio_value(
            raw_appearance, "review_bg_opacity", defaults.review_bg_opacity
        ),
        review_bg_blur=_non_negative_int_value(
            raw_appearance, "review_bg_blur", defaults.review_bg_blur
        ),
        review_overlay=_ratio_value(raw_appearance, "review_overlay", defaults.review_overlay),
        review_image_fit=_choice_string_value(
            raw_appearance, "review_image_fit", defaults.review_image_fit, image_fit_values
        ),
        review_image_position=_string_value(
            raw_appearance, "review_image_position", defaults.review_image_position
        ),
        review_panel_opacity=_ratio_value(
            raw_appearance, "review_panel_opacity", defaults.review_panel_opacity
        ),
        review_corner_radius=_non_negative_int_value(
            raw_appearance, "review_corner_radius", defaults.review_corner_radius
        ),
        input_bg_image_path=_string_value(
            raw_appearance, "input_bg_image_path", defaults.input_bg_image_path
        ),
        input_bg_opacity=_ratio_value(
            raw_appearance, "input_bg_opacity", defaults.input_bg_opacity
        ),
        input_bg_blur=_non_negative_int_value(
            raw_appearance, "input_bg_blur", defaults.input_bg_blur
        ),
        input_overlay=_ratio_value(raw_appearance, "input_overlay", defaults.input_overlay),
        input_image_fit=_choice_string_value(
            raw_appearance, "input_image_fit", defaults.input_image_fit, image_fit_values
        ),
        input_image_position=_string_value(
            raw_appearance, "input_image_position", defaults.input_image_position
        ),
        input_panel_opacity=_ratio_value(
            raw_appearance, "input_panel_opacity", defaults.input_panel_opacity
        ),
        input_corner_radius=_non_negative_int_value(
            raw_appearance, "input_corner_radius", defaults.input_corner_radius
        ),
        debug_bg_image_path=_string_value(
            raw_appearance, "debug_bg_image_path", defaults.debug_bg_image_path
        ),
        debug_bg_opacity=_ratio_value(
            raw_appearance, "debug_bg_opacity", defaults.debug_bg_opacity
        ),
        debug_bg_blur=_non_negative_int_value(
            raw_appearance, "debug_bg_blur", defaults.debug_bg_blur
        ),
        debug_overlay=_ratio_value(raw_appearance, "debug_overlay", defaults.debug_overlay),
        debug_panel_opacity=_ratio_value(
            raw_appearance, "debug_panel_opacity", defaults.debug_panel_opacity
        ),
    )


def save_settings(settings: AppSettings, path: Path | None = None) -> Path:
    """Persist non-secret settings as human-readable UTF-8 JSON."""

    settings_path = path or default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    provider_data = asdict(settings.provider)
    # Never write API keys into settings.json. They belong to env vars or an ignored .env file.
    provider_data.pop("gemini_api_key", None)
    provider_data.pop("openai_api_key", None)
    provider_data.pop("compatible_api_key", None)
    dataset_data = asdict(settings.dataset)
    dataset_data.pop("require_anonymization_before_export", None)
    dataset_data.pop("allow_non_anonymized_export", None)
    dataset_data.pop("capture_store_path", None)
    payload = json.dumps(
        {
            "provider": provider_data,
            "dataset": dataset_data,
            "general": asdict(settings.general),
            "review_hud": asdict(settings.review_hud),
            "input_panel": asdict(settings.input_panel),
            "appearance": asdict(settings.appearance),
        },
        ensure_ascii=False,
        indent=2,
    )
    _atomic_write_text(settings_path, f"{payload}\n")
    return settings_path


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace a settings file only after its complete replacement is durable enough to rename."""

    temporary_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary_path.open("x", encoding="utf-8") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _string_value(values: dict[str, Any], key: str, default: str) -> str:
    value = values.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"The {key} setting must be a string.")
    return value


def _env_or_string_value(
    env: dict[str, str],
    env_key: str,
    values: dict[str, Any],
    value_key: str,
    default: str,
) -> str:
    """Resolve a string with defaults < JSON < .env < process environment precedence."""

    if env_key in env:
        return env[env_key]
    return _string_value(values, value_key, default)


def _number_from_sources(
    values: dict[str, Any],
    env: dict[str, str],
    value_key: str,
    env_key: str,
    default: float,
) -> float:
    if env_key in env and env[env_key] != "":
        return _float_env(env, env_key, default)
    return _positive_number_value(values, value_key, default)


def _int_from_sources(
    values: dict[str, Any],
    env: dict[str, str],
    value_key: str,
    env_key: str,
    default: int,
) -> int:
    if env_key in env and env[env_key] != "":
        return _int_env(env, env_key, default)
    return _positive_int_value(values, value_key, default)


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


def _non_negative_int_value(values: dict[str, Any], key: str, default: int) -> int:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"The {key} setting must be a non-negative integer.")
    return value


def _ratio_value(values: dict[str, Any], key: str, default: float) -> float:
    value = values.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"The {key} setting must be a number from 0 to 1.")
    result = float(value)
    if result < 0 or result > 1:
        raise ValueError(f"The {key} setting must be a number from 0 to 1.")
    return result


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
