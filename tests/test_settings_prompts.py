from PySide6.QtCore import Qt

from uttate.keymap import DEFAULT_BINDINGS, KeyConfig
from uttate.prompts.registry import LocalAIPromptProfile, LocalAIPromptRegistry
from uttate.ui.settings_window import SettingsWindow


def test_settings_window_applies_local_ai_prompt_profile(qtbot, tmp_path) -> None:
    registry = LocalAIPromptRegistry(
        tmp_path / "local_ai_prompts.yaml",
        {
            "default": LocalAIPromptProfile(
                name="default",
                model="",
                prompt="default prompt",
                default_prompt_snapshot="default prompt",
            )
        },
        default_prompt="default prompt",
    )
    window = SettingsWindow(KeyConfig(DEFAULT_BINDINGS), prompt_registry=registry)
    qtbot.addWidget(window)

    assert window.prompt_profile_combo.currentData() == "default"
    assert "起動中に YAML を直接編集しても直ちには反映されません" in window.prompt_notice.text()
    assert window.prompt_close_button.text() == "変更せず閉じる (Escape)"
    assert window.prompt_apply_button.text() == "適用する (Ctrl+R)"
    assert window.prompt_apply_close_button.text() == "変更して閉じる (Ctrl+Enter)"

    window.prompt_editor.setPlainText("edited prompt")
    with qtbot.waitSignal(window.local_ai_prompts_saved, timeout=1000) as blocker:
        qtbot.mouseClick(window.prompt_apply_button, Qt.MouseButton.LeftButton)

    assert blocker.args == [registry]
    assert registry.profile("default").prompt == "edited prompt"
    assert "edited prompt" in registry.path.read_text(encoding="utf-8")
