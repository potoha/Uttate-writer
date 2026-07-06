from uttate.prompts.registry import LocalAIPromptRegistry


def test_prompt_registry_creates_default_yaml(tmp_path) -> None:
    path = tmp_path / "registry" / "promptsf" / "local_ai_prompts.yaml"

    registry = LocalAIPromptRegistry.load(path, default_prompt="default v1")

    assert registry.profile_names() == ["default"]
    assert registry.prompt_for_model("") == "default v1"
    text = path.read_text(encoding="utf-8")
    assert "External edits to this file are read only when Uttate starts" in text
    assert "default v1" in text


def test_prompt_registry_refreshes_profiles_that_still_match_old_default(tmp_path) -> None:
    path = tmp_path / "local_ai_prompts.yaml"
    registry = LocalAIPromptRegistry.load(path, default_prompt="default v1")
    registry.ensure_model_profile("loaded-model")
    registry.save()

    reloaded = LocalAIPromptRegistry.load(path, default_prompt="default v2")

    assert reloaded.profile("default").prompt == "default v2"
    assert reloaded.profile("model_loaded-model").prompt == "default v2"
    assert reloaded.profile("model_loaded-model").default_prompt_snapshot == "default v2"


def test_prompt_registry_preserves_customized_profile_on_default_update(tmp_path) -> None:
    path = tmp_path / "local_ai_prompts.yaml"
    registry = LocalAIPromptRegistry.load(path, default_prompt="default v1")
    profile_name = registry.ensure_model_profile("loaded-model")
    registry.set_prompt(profile_name, "custom model prompt")
    registry.save()

    reloaded = LocalAIPromptRegistry.load(path, default_prompt="default v2")

    assert reloaded.profile(profile_name).prompt == "custom model prompt"
    assert reloaded.profile("default").prompt == "default v2"
