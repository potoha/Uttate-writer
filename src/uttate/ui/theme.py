from __future__ import annotations

import json
import re
import shutil
import zipfile
from contextlib import suppress
from dataclasses import asdict, replace
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import Any

from PySide6.QtWidgets import QWidget

from uttate.config import AppearanceSettings, AppSettings, default_settings_path

BUILT_IN_THEME_IDS = frozenset({"default", "paper", "glass"})
ALLOWED_THEME_EXTENSIONS = frozenset(
    {
        ".json",
        ".css",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".md",
    }
)
FORBIDDEN_THEME_EXTENSIONS = frozenset(
    {
        ".exe",
        ".bat",
        ".cmd",
        ".ps1",
        ".py",
        ".js",
        ".vbs",
        ".dll",
        ".scr",
    }
)
EXTERNAL_URL_PATTERN = re.compile(r"url\(\s*['\"]?https?://", re.IGNORECASE)


class ThemePackageError(ValueError):
    """Raised when a theme package is invalid or unsafe."""


def themes_root() -> Path:
    """Return the writable directory for user-created and imported themes."""

    return default_settings_path().parent / "themes"


def _builtin_themes_root() -> Traversable:
    """Return packaged built-in themes without copying them into user storage."""

    return files("uttate").joinpath("themes")


def _builtin_theme_directory(theme_id: str) -> Traversable | None:
    directory = _builtin_themes_root().joinpath(theme_id)
    css = directory.joinpath("theme.css")
    return directory if directory.is_dir() and css.is_file() else None


def _theme_directory(theme_id: str, root: Path | None = None) -> Path | Traversable:
    if root is not None:
        return root / theme_id
    custom_theme = themes_root() / theme_id
    if custom_theme.is_dir():
        return custom_theme
    return _builtin_theme_directory(theme_id) or custom_theme


def _is_theme_directory(directory: Path | Traversable) -> bool:
    return directory.is_dir() and directory.joinpath("theme.css").is_file()


def _theme_files(directory: Path | Traversable) -> list[tuple[str, Path | Traversable]]:
    files_with_names: list[tuple[str, Path | Traversable]] = []

    def collect(current: Path | Traversable, prefix: str = "") -> None:
        for child in current.iterdir():
            relative = f"{prefix}{child.name}"
            if child.is_dir():
                collect(child, f"{relative}/")
            elif child.is_file():
                files_with_names.append((relative, child))

    collect(directory)
    return files_with_names


def _copy_theme_directory(source: Path | Traversable, destination: Path) -> None:
    for relative, path in _theme_files(source):
        target = destination / Path(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def _read_optional_text(path: Path | Traversable) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def available_theme_presets() -> list[str]:
    presets = {path.name for path in _builtin_themes_root().iterdir() if _is_theme_directory(path)}
    root = themes_root()
    if root.exists():
        presets.update(path.name for path in root.iterdir() if _is_theme_directory(path))
    return sorted(presets) or ["default"]


def theme_directory(theme_id: str, root: Path | None = None) -> Path | Traversable:
    """Return a custom theme directory or a read-only built-in package resource."""

    return _theme_directory(theme_id, root)


def theme_metadata(theme_id: str, root: Path | None = None) -> dict[str, Any]:
    path = _theme_directory(theme_id, root).joinpath("theme.json")
    if not path.is_file():
        return _default_theme_metadata(theme_id)
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise ThemePackageError("theme.json root must be an object.")
    return {**_default_theme_metadata(theme_id), **raw_data}


def appearance_from_theme(theme_id: str, root: Path | None = None) -> AppearanceSettings | None:
    data = theme_metadata(theme_id, root)
    raw_appearance = data.get("appearance")
    if not isinstance(raw_appearance, dict):
        return None
    allowed = {field.name for field in AppearanceSettings.__dataclass_fields__.values()}
    filtered = {key: value for key, value in raw_appearance.items() if key in allowed}
    filtered["theme_preset"] = theme_id
    return AppearanceSettings(**filtered)


def safe_theme_id(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return normalized or "theme"


def unique_theme_id(candidate: str, root: Path | None = None) -> str:
    root = root or themes_root()
    base = safe_theme_id(candidate)
    theme_id = base
    index = 2
    while (root / theme_id).exists() or (root == themes_root() and theme_id in BUILT_IN_THEME_IDS):
        theme_id = f"{base}-{index}"
        index += 1
    return theme_id


def normalized_theme_settings(settings: AppSettings) -> AppSettings:
    presets = available_theme_presets()
    if settings.appearance.theme_preset in presets:
        return settings
    return replace(
        settings,
        appearance=replace(settings.appearance, theme_preset=presets[0]),
    )


def apply_theme(settings: AppSettings, widgets: list[QWidget]) -> None:
    settings = normalized_theme_settings(settings)
    with suppress(OSError):
        write_generated_settings_css(settings.appearance, settings)
    stylesheet = build_qss(settings)
    for widget in widgets:
        widget.setStyleSheet(stylesheet)


def write_generated_settings_css(appearance: AppearanceSettings, settings: AppSettings) -> Path:
    path = default_settings_path().parent / "generated-settings.css"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_generated_settings_css(appearance, settings), encoding="utf-8")
    return path


def render_generated_settings_css(appearance: AppearanceSettings, settings: AppSettings) -> str:
    values = {
        "--uw-font-family": appearance.font_family,
        "--uw-ui-font-size": f"{appearance.ui_font_size}px",
        "--uw-review-font-size": f"{appearance.review_font_size}px",
        "--uw-input-font-size": f"{appearance.input_font_size}px",
        "--uw-queue-font-size": f"{appearance.queue_font_size}px",
        "--uw-shortcut-font-size": f"{appearance.shortcut_font_size}px",
        "--uw-review-bg-image": _css_url(appearance.review_bg_image_path),
        "--uw-review-bg-opacity": str(appearance.review_bg_opacity),
        "--uw-review-bg-blur": f"{appearance.review_bg_blur}px",
        "--uw-review-overlay": str(appearance.review_overlay),
        "--uw-review-width": f"{settings.review_hud.width}px",
        "--uw-review-height": f"{settings.review_hud.height}px",
        "--uw-review-radius": f"{appearance.review_corner_radius}px",
        "--uw-review-panel-opacity": str(appearance.review_panel_opacity),
        "--uw-input-bg-image": _css_url(appearance.input_bg_image_path),
        "--uw-input-bg-opacity": str(appearance.input_bg_opacity),
        "--uw-input-bg-blur": f"{appearance.input_bg_blur}px",
        "--uw-input-overlay": str(appearance.input_overlay),
        "--uw-input-width": f"{settings.input_panel.width}px",
        "--uw-input-height": f"{settings.input_panel.height}px",
        "--uw-input-radius": f"{appearance.input_corner_radius}px",
        "--uw-input-panel-opacity": str(appearance.input_panel_opacity),
        "--uw-debug-bg-image": _css_url(appearance.debug_bg_image_path),
        "--uw-debug-bg-opacity": str(appearance.debug_bg_opacity),
        "--uw-debug-bg-blur": f"{appearance.debug_bg_blur}px",
        "--uw-debug-overlay": str(appearance.debug_overlay),
        "--uw-debug-font-size": f"{appearance.debug_font_size}px",
    }
    lines = [":root {"]
    lines.extend(f"  {name}: {value};" for name, value in values.items())
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def load_css_stack(settings: AppSettings) -> str:
    appearance = normalized_theme_settings(settings).appearance
    theme = _theme_directory(appearance.theme_preset)
    paths: list[Path | Traversable] = [
        _builtin_themes_root().joinpath("base.css"),
        theme.joinpath("theme.css"),
        theme.joinpath("settings.css"),
        default_settings_path().parent / "generated-settings.css",
        Path(appearance.custom_css_path)
        if appearance.custom_css_path
        else default_settings_path().parent / "user-custom.css",
    ]
    return "\n\n".join(text for path in paths if (text := _read_optional_text(path)))


def save_current_as_theme(
    settings: AppSettings,
    *,
    name: str,
    theme_id: str = "",
    author: str = "user",
    version: str = "1.0.0",
    description: str = "",
    preview_image: str = "",
    root: Path | None = None,
) -> str:
    target_root = root or themes_root()
    target_id = unique_theme_id(theme_id or name, target_root)
    _write_theme_from_settings(
        settings,
        target_id=target_id,
        name=name,
        author=author,
        version=version,
        description=description,
        preview_image=preview_image,
        root=target_root,
        overwrite=False,
    )
    return target_id


def update_theme(
    settings: AppSettings,
    *,
    name: str,
    theme_id: str,
    author: str = "user",
    version: str = "1.0.0",
    description: str = "",
    preview_image: str = "",
    root: Path | None = None,
) -> str:
    if theme_id in BUILT_IN_THEME_IDS:
        raise ThemePackageError("Built-in themes cannot be updated directly. Duplicate first.")
    target_root = root or themes_root()
    if not (target_root / theme_id).exists():
        raise ThemePackageError(f"Theme does not exist: {theme_id}")
    _write_theme_from_settings(
        settings,
        target_id=theme_id,
        name=name,
        author=author,
        version=version,
        description=description,
        preview_image=preview_image,
        root=target_root,
        overwrite=True,
    )
    return theme_id


def duplicate_theme(
    source_theme_id: str,
    *,
    name: str = "",
    theme_id: str = "",
    root: Path | None = None,
) -> str:
    target_root = root or themes_root()
    source = _theme_directory(source_theme_id, root)
    if not _is_theme_directory(source):
        raise ThemePackageError(f"Theme does not exist: {source_theme_id}")
    source_meta = theme_metadata(source_theme_id, root)
    target_id = unique_theme_id(theme_id or name or f"{source_theme_id}-copy", target_root)
    target = target_root / target_id
    _copy_theme_directory(source, target)
    meta = {**source_meta}
    meta["theme_id"] = target_id
    meta["name"] = name or f"{source_meta.get('name', source_theme_id)} Copy"
    meta["author"] = meta.get("author", "user")
    (target / "theme.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target_id


def export_theme(theme_id: str, destination: Path, root: Path | None = None) -> Path:
    source = _theme_directory(theme_id, root)
    if not _is_theme_directory(source):
        raise ThemePackageError(f"Theme does not exist: {theme_id}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, path in _theme_files(source):
            if not _is_allowed_theme_member(relative):
                continue
            if relative == "theme.json":
                _validate_theme_json(json.loads(path.read_text(encoding="utf-8")))
            if path.suffix.lower() == ".css" and _contains_external_url(
                path.read_text(encoding="utf-8")
            ):
                raise ThemePackageError("External CSS URLs are not allowed in exported themes.")
            archive.write(path, relative)
    return destination


def import_theme(package_path: Path, root: Path | None = None) -> str:
    target_root = root or themes_root()
    with zipfile.ZipFile(package_path) as archive:
        names = archive.namelist()
        if "theme.json" not in names:
            raise ThemePackageError("Theme package must include theme.json.")
        for name in names:
            _validate_zip_member(name)
        metadata = json.loads(archive.read("theme.json").decode("utf-8"))
        _validate_theme_json(metadata)
        for name in names:
            if name.lower().endswith(".css"):
                css = archive.read(name).decode("utf-8", errors="replace")
                if _contains_external_url(css):
                    raise ThemePackageError("External CSS URLs are not allowed.")
        target_id = unique_theme_id(str(metadata["theme_id"]), target_root)
        target = target_root / target_id
        target.mkdir(parents=True, exist_ok=False)
        for name in names:
            if name.endswith("/"):
                continue
            destination = _safe_extract_path(target, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
        metadata["theme_id"] = target_id
        (target / "theme.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return target_id


def _write_theme_from_settings(
    settings: AppSettings,
    *,
    target_id: str,
    name: str,
    author: str,
    version: str,
    description: str,
    preview_image: str,
    root: Path,
    overwrite: bool,
) -> None:
    target = root / target_id
    if target.exists() and not overwrite:
        raise ThemePackageError(f"Theme already exists: {target_id}")
    target.mkdir(parents=True, exist_ok=True)
    assets = target / "assets"
    assets.mkdir(exist_ok=True)
    appearance = settings.appearance
    source_theme = _theme_directory(appearance.theme_preset, root)
    css_text = _read_optional_text(source_theme.joinpath("theme.css"))
    custom_css = Path(appearance.custom_css_path) if appearance.custom_css_path else None
    if custom_css and custom_css.exists():
        custom_css_text = custom_css.read_text(encoding="utf-8")
        css_text = f"{css_text}\n\n/* Imported custom CSS */\n{custom_css_text}"
    if _contains_external_url(css_text):
        raise ThemePackageError("External CSS URLs are not allowed. Bundle local assets instead.")
    (target / "theme.css").write_text(css_text.strip() + "\n", encoding="utf-8")

    appearance = _appearance_with_local_assets(appearance, assets)
    preview_relative = _copy_optional_asset(preview_image, assets, "preview")
    preview_image = preview_relative
    settings_for_css = replace(
        settings,
        appearance=replace(appearance, theme_preset=target_id, custom_css_path=""),
    )
    (target / "settings.css").write_text(
        render_generated_settings_css(settings_for_css.appearance, settings_for_css),
        encoding="utf-8",
    )
    metadata = _theme_metadata(
        theme_id=target_id,
        name=name or target_id,
        author=author or "user",
        version=version or "1.0.0",
        description=description,
        preview_image=preview_image,
        appearance=settings_for_css.appearance,
    )
    (target / "theme.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {metadata['name']}\n\n{metadata['description']}\n",
        encoding="utf-8",
    )


def _appearance_with_local_assets(
    appearance: AppearanceSettings,
    assets: Path,
) -> AppearanceSettings:
    return replace(
        appearance,
        review_bg_image_path=_copy_optional_asset(
            appearance.review_bg_image_path, assets, "review-bg"
        ),
        input_bg_image_path=_copy_optional_asset(
            appearance.input_bg_image_path, assets, "input-bg"
        ),
        debug_bg_image_path=_copy_optional_asset(
            appearance.debug_bg_image_path, assets, "debug-bg"
        ),
    )


def _copy_optional_asset(source: str, assets: Path, stem: str) -> str:
    if not source:
        return ""
    source_path = Path(source)
    if not source_path.exists() or source_path.suffix.lower() not in ALLOWED_THEME_EXTENSIONS:
        return ""
    destination = assets / f"{stem}{source_path.suffix.lower()}"
    shutil.copy2(source_path, destination)
    return destination.relative_to(assets.parent).as_posix()


def _theme_metadata(
    *,
    theme_id: str,
    name: str,
    author: str,
    version: str,
    description: str,
    preview_image: str,
    appearance: AppearanceSettings,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "theme_id": theme_id,
        "name": name,
        "version": version,
        "author": author,
        "description": description,
        "css": "theme.css",
        "settings_css": "settings.css",
        "assets_dir": "assets",
        "preview_image": preview_image,
        "created_with": "Uttate Writer",
        "supports": {
            "review_hud_background": True,
            "input_panel_background": True,
            "debug_console_background": True,
            "custom_fonts": True,
        },
        "appearance": asdict(appearance),
    }


def _default_theme_metadata(theme_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "theme_id": theme_id,
        "name": theme_id,
        "version": "1.0.0",
        "author": "Uttate Writer",
        "description": "",
        "css": "theme.css",
        "settings_css": "settings.css",
        "assets_dir": "assets",
        "preview_image": "",
        "created_with": "Uttate Writer",
        "supports": {
            "review_hud_background": True,
            "input_panel_background": True,
            "debug_console_background": True,
            "custom_fonts": True,
        },
    }


def _validate_theme_json(data: object) -> None:
    if not isinstance(data, dict):
        raise ThemePackageError("theme.json root must be an object.")
    if data.get("schema_version") != 1:
        raise ThemePackageError("Unsupported theme schema_version.")
    theme_id = data.get("theme_id")
    if not isinstance(theme_id, str) or safe_theme_id(theme_id) != theme_id:
        raise ThemePackageError("theme_id must be a safe slug.")
    preview_image = data.get("preview_image", "")
    if isinstance(preview_image, str) and _is_absolute_or_parent_path(preview_image):
        raise ThemePackageError("Theme metadata must not contain absolute paths.")
    appearance = data.get("appearance", {})
    if isinstance(appearance, dict):
        for key in (
            "custom_css_path",
            "review_bg_image_path",
            "input_bg_image_path",
            "debug_bg_image_path",
        ):
            value = appearance.get(key, "")
            if isinstance(value, str) and _is_absolute_or_parent_path(value):
                raise ThemePackageError("Theme appearance must not contain absolute paths.")


def _validate_zip_member(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ThemePackageError("Unsafe path in theme package.")
    if name.endswith("/"):
        return
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_THEME_EXTENSIONS or (suffix and suffix not in ALLOWED_THEME_EXTENSIONS):
        raise ThemePackageError(f"File type is not allowed: {suffix}")
    if not _is_allowed_theme_member(name):
        raise ThemePackageError(f"Theme package contains unsupported file: {name}")


def _safe_extract_path(root: Path, name: str) -> Path:
    destination = (root / Path(*PurePosixPath(name).parts)).resolve()
    root_resolved = root.resolve()
    if root_resolved not in destination.parents and destination != root_resolved:
        raise ThemePackageError("Unsafe path in theme package.")
    return destination


def _is_allowed_theme_member(name: str) -> bool:
    path = PurePosixPath(name)
    if path.name == "theme.json":
        return True
    if path.name in {"theme.css", "settings.css", "generated-settings.css", "README.md"}:
        return True
    return path.parts[:1] == ("assets",) and path.suffix.lower() in ALLOWED_THEME_EXTENSIONS


def _contains_external_url(css_text: str) -> bool:
    return bool(EXTERNAL_URL_PATTERN.search(css_text))


def _is_absolute_or_parent_path(value: str) -> bool:
    if not value:
        return False
    path = PurePosixPath(value.replace("\\", "/"))
    return path.is_absolute() or ".." in path.parts or bool(re.match(r"^[A-Za-z]:/", str(path)))


def build_qss(settings: AppSettings) -> str:
    appearance = normalized_theme_settings(settings).appearance
    loaded_css = load_css_stack(settings).replace("*/", "* /")
    font = _qss_string(appearance.font_family)
    review_bg = _surface_background(
        appearance.review_bg_image_path,
        appearance.review_overlay,
        appearance.review_image_fit,
        appearance.review_image_position,
    )
    input_bg = _surface_background(
        appearance.input_bg_image_path,
        appearance.input_overlay,
        appearance.input_image_fit,
        appearance.input_image_position,
    )
    debug_bg = _surface_background(
        appearance.debug_bg_image_path,
        appearance.debug_overlay,
        "cover",
        "center",
    )
    return f"""
/* Loaded CSS stack for theme authors:
{loaded_css}
*/
QWidget {{
    font-family: {font}, sans-serif;
    font-size: {appearance.ui_font_size}px;
}}
QWidget#review-hud {{
    {review_bg}
    border-radius: {appearance.review_corner_radius}px;
    font-size: {appearance.review_font_size}px;
}}
QWidget#input-panel {{
    {input_bg}
    border-radius: {appearance.input_corner_radius}px;
    font-size: {appearance.input_font_size}px;
}}
QWidget#debug-console {{
    {debug_bg}
    font-size: {appearance.debug_font_size}px;
}}
QWidget#settings-window {{
    background-color: rgba(248, 250, 252, 245);
}}
QWidget#dataset-review-window {{
    background-color: rgba(248, 250, 252, 245);
}}
QFrame#dataset-card {{
    background-color: rgba(255, 255, 255, 235);
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 6px;
}}
QLabel#datasetExternalApiBadge {{
    color: #92400e;
    font-weight: 600;
}}
QListWidget#queue-item {{
    font-size: {appearance.queue_font_size}px;
}}
QPlainTextEdit#preview-text, QPlainTextEdit#reviewCandidateA, QPlainTextEdit#reviewCandidateB {{
    font-size: {appearance.review_font_size}px;
}}
QPlainTextEdit#roughInputEditor {{
    font-size: {appearance.input_font_size}px;
}}
QLabel#shortcut-bar {{
    font-size: {appearance.shortcut_font_size}px;
    color: #475569;
}}
QLabel#inputPanelWarning {{
    font-size: {appearance.shortcut_font_size}px;
    color: #92400e;
}}
QPlainTextEdit, QListWidget, QComboBox, QLineEdit, QSpinBox {{
    background-color: rgba(255, 255, 255, 235);
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px;
}}
QPushButton {{
    border: 1px solid #94a3b8;
    border-radius: 6px;
    padding: 5px 9px;
    background-color: rgba(255, 255, 255, 230);
}}
QPushButton:hover {{
    background-color: rgba(241, 245, 249, 245);
}}
"""


def _surface_background(
    image_path: str,
    overlay: float,
    image_fit: str,
    image_position: str,
) -> str:
    lines = [f"background-color: {_rgba(255, 255, 255, overlay)};"]
    if image_path:
        path = Path(image_path).as_posix()
        if image_fit == "stretch":
            lines.append(f'border-image: url("{path}") 0 0 0 0 stretch stretch;')
        else:
            repeat = "repeat" if image_fit == "tile" else "no-repeat"
            lines.append(f'background-image: url("{path}");')
            lines.append(f"background-repeat: {repeat};")
            lines.append(f"background-position: {image_position};")
    return "\n    ".join(lines)


def _rgba(red: int, green: int, blue: int, alpha_ratio: float) -> str:
    alpha = max(0, min(255, round(alpha_ratio * 255)))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _qss_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _css_url(value: str) -> str:
    if not value:
        return "none"
    return f'url("{Path(value).as_posix()}")'
