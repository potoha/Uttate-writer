from uttate.prompts.registry import LocalAIPromptProfile, LocalAIPromptRegistry
from uttate.ui.main_window import MainWindow


def test_main_window_smoke(qtbot, tmp_path) -> None:
    prompt_registry = LocalAIPromptRegistry(
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
    window = MainWindow(prompt_registry=prompt_registry)
    qtbot.addWidget(window)

    assert window.windowTitle() == "Uttate Writer"
    assert window.centralWidget() is not None
    assert window.statusBar().currentMessage() == "Ready"
