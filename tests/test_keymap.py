from __future__ import annotations

from uttate.keymap import KeyConfig


def test_keyconfig_yaml_overrides_combination_key(tmp_path) -> None:
    config_path = tmp_path / "keyconfig.yaml"
    config_path.write_text(
        """
version: 1
modes:
  input:
    commit_chunk:
      label: "Commit chunk"
      keys:
        - "Ctrl+Enter"
      role: "Send chunk"
""",
        encoding="utf-8",
    )

    config = KeyConfig.load(config_path)

    assert config.keys_for("input", "commit_chunk") == ("Ctrl+Enter",)


def test_keyconfig_save_keeps_cheat_sheet_text(tmp_path) -> None:
    config_path = tmp_path / "keyconfig.yaml"

    KeyConfig().save(config_path)

    written = config_path.read_text(encoding="utf-8")
    assert "This file is both configuration and a keyboard cheat sheet." in written
    assert "open_settings" in written
    assert '"F12"' in written
