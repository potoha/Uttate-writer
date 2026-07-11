from __future__ import annotations

import json
import zipfile

import pytest

from uttate.config import AppearanceSettings, AppSettings, ProviderSettings
from uttate.ui.theme import (
    ThemePackageError,
    available_theme_presets,
    duplicate_theme,
    export_theme,
    import_theme,
    load_css_stack,
    save_current_as_theme,
    theme_directory,
    themes_root,
    update_theme,
)


def test_save_current_as_theme_copies_assets_and_uses_relative_paths(tmp_path) -> None:
    review_bg = tmp_path / "private-review.png"
    review_bg.write_bytes(b"png")
    settings = AppSettings(
        provider=ProviderSettings(openai_api_key="secret-openai"),
        appearance=AppearanceSettings(
            theme_preset="default",
            font_family="Arial",
            review_bg_image_path=str(review_bg),
            review_overlay=0.75,
        ),
    )

    theme_id = save_current_as_theme(
        settings,
        name="My Paper Custom",
        author="me",
        description="Custom writing theme.",
        root=tmp_path / "themes",
    )

    theme_dir = tmp_path / "themes" / theme_id
    metadata = json.loads((theme_dir / "theme.json").read_text(encoding="utf-8"))

    assert theme_id == "my-paper-custom"
    assert metadata["schema_version"] == 1
    assert metadata["theme_id"] == "my-paper-custom"
    assert metadata["name"] == "My Paper Custom"
    assert metadata["appearance"]["review_bg_image_path"] == "assets/review-bg.png"
    assert (theme_dir / "assets" / "review-bg.png").exists()
    assert "secret-openai" not in (theme_dir / "theme.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in (theme_dir / "theme.json").read_text(encoding="utf-8")


def test_save_current_as_theme_drops_uncopied_absolute_preview_path(tmp_path) -> None:
    missing_preview = tmp_path / "missing-preview.png"
    theme_id = save_current_as_theme(
        AppSettings(),
        name="Preview Safe",
        preview_image=str(missing_preview),
        root=tmp_path / "themes",
    )

    metadata_text = (tmp_path / "themes" / theme_id / "theme.json").read_text(encoding="utf-8")
    metadata = json.loads(metadata_text)

    assert metadata["preview_image"] == ""
    assert str(tmp_path) not in metadata_text


def test_update_builtin_theme_is_rejected(tmp_path) -> None:
    with pytest.raises(ThemePackageError, match="Built-in"):
        update_theme(
            AppSettings(),
            name="Default",
            theme_id="default",
            root=tmp_path / "themes",
        )


def test_duplicate_theme_creates_editable_copy(tmp_path) -> None:
    source = tmp_path / "themes" / "default"
    source.mkdir(parents=True)
    (source / "theme.css").write_text("/* default */\n", encoding="utf-8")
    (source / "theme.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "theme_id": "default",
                "name": "Default",
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )

    theme_id = duplicate_theme("default", name="My Default", root=tmp_path / "themes")

    assert theme_id == "my-default"
    assert (tmp_path / "themes" / theme_id / "theme.css").exists()
    metadata = json.loads(
        (tmp_path / "themes" / theme_id / "theme.json").read_text(encoding="utf-8")
    )
    assert metadata["theme_id"] == "my-default"
    assert metadata["name"] == "My Default"


def test_export_theme_zip_contains_only_theme_files(tmp_path) -> None:
    settings = AppSettings(appearance=AppearanceSettings(theme_preset="default"))
    theme_id = save_current_as_theme(
        settings,
        name="Exportable",
        root=tmp_path / "themes",
    )
    (tmp_path / "themes" / theme_id / "logs").mkdir()
    (tmp_path / "themes" / theme_id / "logs" / "secret.log").write_text("secret")
    destination = tmp_path / "export.uttate-theme.zip"

    export_theme(theme_id, destination, root=tmp_path / "themes")

    with zipfile.ZipFile(destination) as archive:
        names = set(archive.namelist())
        payload = "\n".join(archive.read(name).decode("utf-8", errors="ignore") for name in names)

    assert "theme.json" in names
    assert "theme.css" in names
    assert "settings.css" in names
    assert "README.md" in names
    assert "logs/secret.log" not in names
    assert "OPENAI_API_KEY" not in payload
    assert "secret.log" not in payload


def test_import_theme_rejects_unsafe_zip_members(tmp_path) -> None:
    package = tmp_path / "bad.uttate-theme.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "theme.json",
            json.dumps({"schema_version": 1, "theme_id": "bad-theme"}),
        )
        archive.writestr("../escape.css", "bad")

    with pytest.raises(ThemePackageError, match="Unsafe"):
        import_theme(package, root=tmp_path / "themes")


def test_import_theme_rejects_scripts_and_external_urls(tmp_path) -> None:
    script_package = tmp_path / "script.uttate-theme.zip"
    with zipfile.ZipFile(script_package, "w") as archive:
        archive.writestr(
            "theme.json",
            json.dumps({"schema_version": 1, "theme_id": "script-theme"}),
        )
        archive.writestr("assets/run.ps1", "Write-Host nope")

    with pytest.raises(ThemePackageError, match="not allowed"):
        import_theme(script_package, root=tmp_path / "themes")

    url_package = tmp_path / "url.uttate-theme.zip"
    with zipfile.ZipFile(url_package, "w") as archive:
        archive.writestr(
            "theme.json",
            json.dumps({"schema_version": 1, "theme_id": "url-theme"}),
        )
        archive.writestr("theme.css", "body { background: url(https://example.com/a.png); }")

    with pytest.raises(ThemePackageError, match="External CSS URLs"):
        import_theme(url_package, root=tmp_path / "themes")


def test_import_theme_rejects_absolute_metadata_paths(tmp_path) -> None:
    package = tmp_path / "absolute-path.uttate-theme.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "theme.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "theme_id": "absolute-path",
                    "preview_image": "C:/Users/example/private.png",
                }
            ),
        )
        archive.writestr("theme.css", "/* ok */")

    with pytest.raises(ThemePackageError, match="absolute paths"):
        import_theme(package, root=tmp_path / "themes")


def test_import_theme_resolves_theme_id_collisions(tmp_path) -> None:
    package = tmp_path / "theme.uttate-theme.zip"
    (tmp_path / "themes" / "shared-theme").mkdir(parents=True)
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "theme.json",
            json.dumps({"schema_version": 1, "theme_id": "shared-theme"}),
        )
        archive.writestr("theme.css", "/* ok */")

    theme_id = import_theme(package, root=tmp_path / "themes")

    assert theme_id == "shared-theme-2"
    assert (tmp_path / "themes" / "shared-theme-2" / "theme.json").exists()


def test_builtin_theme_css_uses_package_resources_without_creating_user_themes(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("UTTATE_CONFIG_DIR", str(tmp_path / "config"))

    assert {"default", "paper", "glass"}.issubset(available_theme_presets())
    assert "background-color" in load_css_stack(AppSettings())
    assert theme_directory("default").joinpath("theme.css").is_file()
    assert not themes_root().exists()


def test_duplicate_builtin_theme_writes_only_to_user_theme_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UTTATE_CONFIG_DIR", str(tmp_path / "config"))

    theme_id = duplicate_theme("default", name="My Default")

    assert theme_id == "my-default"
    assert (themes_root() / theme_id / "theme.css").exists()
    assert theme_directory("default").joinpath("theme.css").is_file()
