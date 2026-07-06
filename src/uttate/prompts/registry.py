from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from uttate.config import default_settings_path

PROMPT_REGISTRY_NOTICE = (
    "External edits to this file are read only when Uttate starts. "
    "Changes applied from the settings prompt console are saved and reflected immediately."
)


@dataclass(slots=True)
class LocalAIPromptProfile:
    name: str
    model: str
    prompt: str
    default_prompt_snapshot: str


class LocalAIPromptRegistry:
    """Editable Local AI prompt profiles backed by one small YAML file."""

    def __init__(
        self,
        path: Path,
        profiles: dict[str, LocalAIPromptProfile],
        *,
        default_prompt: str,
    ) -> None:
        self.path = path
        self.profiles = profiles
        self.default_prompt = default_prompt

    @classmethod
    def load(
        cls,
        path: Path | None = None,
        *,
        default_prompt: str | None = None,
    ) -> LocalAIPromptRegistry:
        registry_path = path or default_prompt_registry_path()
        current_default = (default_prompt or load_default_system_prompt()).strip()
        profiles = _read_profiles(registry_path)
        registry = cls(registry_path, profiles, default_prompt=current_default)
        changed = registry._ensure_default_profile()
        changed = registry._refresh_profiles_for_default_update() or changed
        if changed or not registry_path.exists():
            registry.save()
        return registry

    def profile_names(self) -> list[str]:
        names = list(self.profiles)
        if "default" in names:
            names.remove("default")
            return ["default", *names]
        return names

    def profile(self, name: str) -> LocalAIPromptProfile:
        return self.profiles[name]

    def prompt_for_model(self, model: str) -> str:
        model = model.strip()
        if model:
            for profile in self.profiles.values():
                if profile.model == model:
                    return profile.prompt
        return self.profiles["default"].prompt

    def ensure_model_profile(self, model: str) -> str:
        model = model.strip()
        if not model:
            self._ensure_default_profile()
            return "default"
        for name, profile in self.profiles.items():
            if profile.model == model:
                return name

        name = _unique_profile_name(self.profiles, _profile_name_for_model(model))
        self.profiles[name] = LocalAIPromptProfile(
            name=name,
            model=model,
            prompt=self.profiles["default"].prompt,
            default_prompt_snapshot=self.default_prompt,
        )
        self.save()
        return name

    def set_prompt(self, name: str, prompt: str) -> None:
        if name not in self.profiles:
            raise KeyError(name)
        self.profiles[name].prompt = prompt.strip()

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_dump_profiles(self.profiles), encoding="utf-8")
        return self.path

    def _ensure_default_profile(self) -> bool:
        if "default" in self.profiles:
            return False
        self.profiles["default"] = LocalAIPromptProfile(
            name="default",
            model="",
            prompt=self.default_prompt,
            default_prompt_snapshot=self.default_prompt,
        )
        return True

    def _refresh_profiles_for_default_update(self) -> bool:
        changed = False
        for profile in self.profiles.values():
            old_snapshot = profile.default_prompt_snapshot.strip()
            if profile.prompt.strip() == old_snapshot and old_snapshot != self.default_prompt:
                profile.prompt = self.default_prompt
                profile.default_prompt_snapshot = self.default_prompt
                changed = True
            elif not old_snapshot and profile.prompt.strip() == self.default_prompt:
                profile.default_prompt_snapshot = self.default_prompt
                changed = True
        return changed


def default_prompt_registry_path() -> Path:
    return default_settings_path().parent / "registry" / "promptsf" / "local_ai_prompts.yaml"


def load_default_system_prompt() -> str:
    return (
        resources.files("uttate.prompts")
        .joinpath("reading_normalizer.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def _read_profiles(path: Path) -> dict[str, LocalAIPromptProfile]:
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8").splitlines()
    profiles: dict[str, LocalAIPromptProfile] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("  ") or line.startswith("    "):
            index += 1
            continue
        name = line.strip().removesuffix(":")
        if not name or name == "profiles":
            index += 1
            continue
        index += 1
        values: dict[str, str] = {"model": "", "prompt": "", "default_prompt_snapshot": ""}
        while index < len(lines):
            current = lines[index]
            if current.startswith("  ") and not current.startswith("    "):
                break
            stripped = current.strip()
            if stripped.startswith("model:"):
                values["model"] = _unquote_scalar(stripped.removeprefix("model:").strip())
                index += 1
                continue
            if stripped in {"prompt: |", "default_prompt_snapshot: |"}:
                key = stripped.removesuffix(": |")
                index += 1
                block: list[str] = []
                while index < len(lines) and (
                    lines[index].startswith("      ") or not lines[index].strip()
                ):
                    block.append(lines[index][6:] if lines[index].startswith("      ") else "")
                    index += 1
                values[key] = "\n".join(block).strip()
                continue
            index += 1
        profiles[name] = LocalAIPromptProfile(
            name=name,
            model=values["model"],
            prompt=values["prompt"],
            default_prompt_snapshot=values["default_prompt_snapshot"],
        )
    return profiles


def _dump_profiles(profiles: dict[str, LocalAIPromptProfile]) -> str:
    lines = [
        "# Uttate Local AI prompt profiles.",
        f"# {PROMPT_REGISTRY_NOTICE}",
        "profiles:",
    ]
    for name in _ordered_profile_names(profiles):
        profile = profiles[name]
        lines.extend(
            [
                f"  {name}:",
                f'    model: "{_escape_scalar(profile.model)}"',
                "    prompt: |",
                *_dump_block(profile.prompt),
                "    default_prompt_snapshot: |",
                *_dump_block(profile.default_prompt_snapshot),
            ]
        )
    return "\n".join(lines) + "\n"


def _ordered_profile_names(profiles: dict[str, LocalAIPromptProfile]) -> list[str]:
    names = list(profiles)
    if "default" in names:
        names.remove("default")
        return ["default", *names]
    return names


def _dump_block(value: str) -> list[str]:
    text = value.rstrip("\n")
    if not text:
        return ["      "]
    return [f"      {line}" for line in text.splitlines()]


def _escape_scalar(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _unquote_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _profile_name_for_model(model: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_-]+", "_", model).strip("_").lower()
    return f"model_{slug}" if slug else "model_local_ai"


def _unique_profile_name(
    profiles: dict[str, LocalAIPromptProfile],
    preferred_name: str,
) -> str:
    if preferred_name not in profiles:
        return preferred_name
    suffix = 2
    while f"{preferred_name}_{suffix}" in profiles:
        suffix += 1
    return f"{preferred_name}_{suffix}"
