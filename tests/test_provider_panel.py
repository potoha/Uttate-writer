from uttate.config import ProviderSettings
from uttate.ui.provider_panel import ProviderPanel


def test_provider_panel_shows_current_model(qtbot) -> None:
    panel = ProviderPanel(ProviderSettings(type="gemini", gemini_model="gemini-test"))
    qtbot.addWidget(panel)

    assert panel.provider_combo.currentData() == "gemini"
    assert panel.model_label.text() == "Model: gemini-test"


def test_provider_panel_exposes_only_user_facing_providers(qtbot) -> None:
    panel = ProviderPanel(ProviderSettings())
    qtbot.addWidget(panel)

    provider_ids = [
        panel.provider_combo.itemData(index) for index in range(panel.provider_combo.count())
    ]

    assert provider_ids == ["local_ai", "openai", "gemini"]
    assert "lmstudio" not in provider_ids
    assert "mock" not in provider_ids


def test_provider_panel_emits_selected_provider(qtbot) -> None:
    panel = ProviderPanel(ProviderSettings())
    qtbot.addWidget(panel)

    with qtbot.waitSignal(panel.provider_change_requested, timeout=1000) as blocker:
        panel.provider_combo.setCurrentIndex(panel.provider_combo.findData("openai"))

    assert blocker.args == ["openai"]
