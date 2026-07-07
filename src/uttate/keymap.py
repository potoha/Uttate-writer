from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

GLOBAL_MODE = "global"


@dataclass(frozen=True, slots=True)
class KeyBinding:
    mode: str
    action: str
    label: str
    keys: tuple[str, ...]
    role: str
    note: str = ""


def default_keyconfig_path() -> Path:
    configured_path = os.environ.get("UTTATE_KEYCONFIG_PATH")
    if configured_path:
        return Path(configured_path)
    return Path.cwd() / "keyconfig.yaml"


class KeyConfig:
    def __init__(self, bindings: list[KeyBinding] | None = None) -> None:
        source = bindings if bindings is not None else DEFAULT_BINDINGS
        self._bindings: dict[tuple[str, str], KeyBinding] = {
            (binding.mode, binding.action): binding for binding in source
        }

    @classmethod
    def load(cls, path: Path | None = None) -> KeyConfig:
        config = cls()
        config_path = path or default_keyconfig_path()
        if not config_path.exists():
            return config

        raw_keys = _read_key_yaml(config_path)
        for (mode, action), keys in raw_keys.items():
            if (mode, action) not in config._bindings:
                continue
            config.set_keys(mode, action, keys)
        return config

    def save(self, path: Path | None = None) -> Path:
        config_path = path or default_keyconfig_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(self.to_yaml(), encoding="utf-8")
        return config_path

    def bindings(self, mode: str | None = None) -> list[KeyBinding]:
        values = sorted(
            self._bindings.values(),
            key=lambda item: (_mode_order(item.mode), item.label),
        )
        if mode is None:
            return values
        return [binding for binding in values if binding.mode == mode]

    def binding(self, mode: str, action: str) -> KeyBinding:
        return self._bindings[(mode, action)]

    def keys_for(self, mode: str, action: str) -> tuple[str, ...]:
        return self.binding(mode, action).keys

    def set_keys(self, mode: str, action: str, keys: tuple[str, ...] | list[str]) -> None:
        binding = self.binding(mode, action)
        normalized_keys = tuple(
            key for key in (normalize_key_sequence(raw_key) for raw_key in keys) if key
        )
        self._bindings[(mode, action)] = KeyBinding(
            mode=binding.mode,
            action=binding.action,
            label=binding.label,
            keys=normalized_keys,
            role=binding.role,
            note=binding.note,
        )

    def action_for(self, mode: str, event: QKeyEvent) -> str | None:
        sequence = key_sequence_from_event(event)
        if sequence is None:
            return None
        for binding in self.bindings(mode):
            if sequence in binding.keys:
                return binding.action
        return None

    def find_conflicts(self) -> list[str]:
        conflicts: list[str] = []
        mode_keys: dict[tuple[str, str], list[KeyBinding]] = {}
        global_keys: dict[str, list[KeyBinding]] = {}

        for binding in self._bindings.values():
            for key in binding.keys:
                if binding.mode == GLOBAL_MODE:
                    global_keys.setdefault(key, []).append(binding)
                mode_keys.setdefault((binding.mode, key), []).append(binding)

        for (_mode, _key), bindings in sorted(mode_keys.items()):
            if len(bindings) > 1:
                conflicts.append(_conflict_text(_key, bindings))

        for key, global_bindings in sorted(global_keys.items()):
            for (mode, mode_key), mode_bindings in sorted(mode_keys.items()):
                if mode == GLOBAL_MODE or mode_key != key:
                    continue
                conflicts.append(_conflict_text(key, [*global_bindings, *mode_bindings]))
        return conflicts

    def to_yaml(self) -> str:
        lines = [
            "# Uttate Writer key configuration",
            "#",
            "# This file is both configuration and a keyboard cheat sheet.",
            "# You can edit keys here, but the Settings window is safer for combination keys.",
            "# Key examples: Enter, Shift+Enter, Ctrl+Enter, Escape, Space, F2, F12, Up, Down.",
            "#",
            "version: 1",
            "modes:",
        ]
        current_mode: str | None = None
        for binding in self.bindings():
            if binding.mode != current_mode:
                current_mode = binding.mode
                lines.extend(["", f"  {binding.mode}:"])
            lines.extend(
                [
                    f"    {binding.action}:",
                    f'      label: "{_escape_yaml(binding.label)}"',
                    "      keys:",
                    *[f'        - "{_escape_yaml(key)}"' for key in binding.keys],
                    f'      role: "{_escape_yaml(binding.role)}"',
                ]
            )
            if binding.note:
                lines.append(f'      note: "{_escape_yaml(binding.note)}"')
        lines.append("")
        return "\n".join(lines)


def key_sequence_from_event(event: QKeyEvent) -> str | None:
    key = event.key()
    if key in {
        Qt.Key.Key_Control,
        Qt.Key.Key_Shift,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
        Qt.Key.Key_unknown,
    }:
        return None

    key_name = _key_name(key)
    if key_name is None:
        key_name = QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)
    if not key_name:
        return None

    parts: list[str] = []
    modifiers = event.modifiers()
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        parts.append("Ctrl")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        parts.append("Alt")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        parts.append("Shift")
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        parts.append("Meta")
    parts.append(key_name)
    return "+".join(parts)


def normalize_key_sequence(raw_key: str) -> str:
    parts = [part.strip() for part in raw_key.strip().strip('"').strip("'").split("+")]
    parts = [part for part in parts if part]
    if not parts:
        return ""

    modifiers: list[str] = []
    key = ""
    aliases = {
        "control": "Ctrl",
        "ctrl": "Ctrl",
        "alt": "Alt",
        "option": "Alt",
        "shift": "Shift",
        "meta": "Meta",
        "cmd": "Meta",
        "command": "Meta",
        "return": "Enter",
        "enter": "Enter",
        "esc": "Escape",
        "escape": "Escape",
        "space": "Space",
        "del": "Delete",
        "delete": "Delete",
        "backspace": "Backspace",
        "tab": "Tab",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "comma": ",",
    }
    for part in parts:
        normalized = aliases.get(part.lower(), part)
        if normalized in {"Ctrl", "Alt", "Shift", "Meta"}:
            if normalized not in modifiers:
                modifiers.append(normalized)
        else:
            key = (
                normalized.upper() if len(normalized) == 1 and normalized.isalpha() else normalized
            )

    ordered_modifiers = [
        modifier for modifier in ("Ctrl", "Alt", "Shift", "Meta") if modifier in modifiers
    ]
    return "+".join([*ordered_modifiers, key]) if key else ""


def _read_key_yaml(path: Path) -> dict[tuple[str, str], tuple[str, ...]]:
    result: dict[tuple[str, str], tuple[str, ...]] = {}
    current_mode: str | None = None
    current_action: str | None = None
    reading_keys = False
    keys: list[str] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if indent == 2 and stripped.endswith(":"):
            if current_mode and current_action and keys:
                result[(current_mode, current_action)] = tuple(keys)
            current_mode = stripped[:-1]
            current_action = None
            keys = []
            reading_keys = False
            continue
        if indent == 4 and stripped.endswith(":") and current_mode:
            if current_action and keys:
                result[(current_mode, current_action)] = tuple(keys)
            current_action = stripped[:-1]
            keys = []
            reading_keys = False
            continue
        if indent == 6 and stripped == "keys:":
            reading_keys = True
            continue
        if reading_keys and indent >= 8 and stripped.startswith("-"):
            value = stripped[1:].strip()
            if value:
                keys.append(normalize_key_sequence(value))
            continue
        if indent <= 6:
            reading_keys = False

    if current_mode and current_action and keys:
        result[(current_mode, current_action)] = tuple(keys)
    return result


def _key_name(key: int) -> str | None:
    special = {
        Qt.Key.Key_Return: "Enter",
        Qt.Key.Key_Enter: "Enter",
        Qt.Key.Key_Escape: "Escape",
        Qt.Key.Key_Space: "Space",
        Qt.Key.Key_Backspace: "Backspace",
        Qt.Key.Key_Delete: "Delete",
        Qt.Key.Key_Up: "Up",
        Qt.Key.Key_Down: "Down",
        Qt.Key.Key_Left: "Left",
        Qt.Key.Key_Right: "Right",
        Qt.Key.Key_Tab: "Tab",
        Qt.Key.Key_Backtab: "Tab",
        Qt.Key.Key_Comma: ",",
    }
    if key in special:
        return special[key]
    for number in range(1, 13):
        if key == int(getattr(Qt.Key, f"Key_F{number}")):
            return f"F{number}"
    if int(Qt.Key.Key_A) <= key <= int(Qt.Key.Key_Z):
        return chr(ord("A") + key - int(Qt.Key.Key_A))
    if int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
        return chr(ord("0") + key - int(Qt.Key.Key_0))
    return None


def _mode_order(mode: str) -> int:
    order = {GLOBAL_MODE: 0, "input": 1, "review": 2, "candidate_edit": 3}
    return order.get(mode, 99)


def _escape_yaml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _conflict_text(key: str, bindings: list[KeyBinding]) -> str:
    labels = ", ".join(f"{binding.mode}.{binding.action}" for binding in bindings)
    return f"{key}: {labels}"


DEFAULT_BINDINGS: list[KeyBinding] = [
    KeyBinding(
        GLOBAL_MODE,
        "open_settings",
        "Open settings",
        ("F12",),
        "Open the key configuration window in a separate window.",
        "This is available from the main window and mirrors the Settings button.",
    ),
    KeyBinding(
        GLOBAL_MODE,
        "toggle_input_review",
        "Toggle input/review",
        ("F2",),
        "Switch between Input mode and Review mode.",
        "In Candidate edit mode this cancels the edit and returns to Review mode.",
    ),
    KeyBinding(
        GLOBAL_MODE,
        "toggle_debug_console",
        "Toggle debug console",
        ("Ctrl+D",),
        "Show or hide the diagnostic console.",
        "Normal writing keeps this hidden so the HUD stays small.",
    ),
    KeyBinding(
        "input",
        "commit_chunk",
        "Commit chunk",
        ("Enter",),
        "Send the current rough input chunk to the conversion queue.",
        "The editor clears immediately so you can keep writing while conversion runs.",
    ),
    KeyBinding(
        "input",
        "insert_newline",
        "Insert newline",
        ("Shift+Enter",),
        "Insert a normal line break without committing the chunk.",
    ),
    KeyBinding(
        "input",
        "send_or_convert",
        "Send or convert",
        ("Ctrl+Enter",),
        "Send the current InputPanel text through the same action as the Send button.",
    ),
    KeyBinding(
        "input",
        "insert_chunk_separator",
        "Insert chunk separator",
        ("Space",),
        "Insert the Uttate rough-input separator ` | ` instead of IME conversion.",
    ),
    KeyBinding(
        "input",
        "insert_space",
        "Insert real space",
        ("Shift+Space",),
        "Insert a normal half-width space.",
    ),
    KeyBinding(
        "input",
        "clear_or_hide",
        "Clear or hide",
        ("Escape",),
        "Clear the input if it has text; otherwise close the transient UI.",
    ),
    KeyBinding(
        "review",
        "move_previous_chunk",
        "Previous chunk",
        ("Up",),
        "Move to the previous actionable review chunk.",
    ),
    KeyBinding(
        "review",
        "move_next_chunk",
        "Next chunk",
        ("Down",),
        "Move to the next actionable review chunk.",
    ),
    KeyBinding(
        "review",
        "cycle_candidate",
        "Cycle candidate",
        ("Space",),
        "Preview the other candidate, or move to the next chunk if no alternate exists.",
        "The project spec may later move this to Tab; the UI can already change it.",
    ),
    KeyBinding(
        "review",
        "accept_candidate",
        "Accept candidate",
        ("Enter",),
        "Adopt the currently previewed candidate and copy it to the clipboard.",
    ),
    KeyBinding(
        "review",
        "accept_candidate_for_dataset",
        "Accept candidate for dataset",
        ("Shift+Enter",),
        "Adopt the currently previewed candidate, copy it, and add it to dataset candidates.",
        "This only records data when dataset capture is enabled in Settings.",
    ),
    KeyBinding(
        "review",
        "reject_chunk",
        "Reject chunk",
        ("Backspace", "Delete"),
        "Reject the selected pending, edited, or failed chunk.",
    ),
    KeyBinding(
        "review",
        "edit_as_input",
        "Edit as input",
        ("E",),
        "Copy the selected candidate into Input mode for rewriting.",
    ),
    KeyBinding(
        "review",
        "edit_candidate",
        "Edit candidate",
        ("F",),
        "Edit the selected candidate directly in Candidate edit mode.",
    ),
    KeyBinding(
        "review",
        "reconvert_chunk",
        "Reconvert chunk",
        ("R",),
        "Send the selected chunk back through conversion.",
    ),
    KeyBinding(
        "review",
        "return_to_input",
        "Return to input",
        ("Escape",),
        "Leave Review mode and return to writing.",
    ),
    KeyBinding(
        "candidate_edit",
        "accept_edit",
        "Accept edit",
        ("Enter",),
        "Adopt the edited candidate and copy it to the clipboard.",
    ),
    KeyBinding(
        "candidate_edit",
        "reconvert_edited_text",
        "Reconvert edited text",
        ("Ctrl+Enter",),
        "Use the edited text as raw input and send it through conversion again.",
    ),
    KeyBinding(
        "candidate_edit",
        "cancel_edit",
        "Cancel edit",
        ("Escape", "F2"),
        "Discard the temporary candidate edit and return to Review mode.",
    ),
    KeyBinding(
        "candidate_edit",
        "insert_space",
        "Insert space",
        ("Space",),
        "Insert a normal space while editing a candidate.",
    ),
]
