"""Saved Windows dictation shortcut preferences."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass

from .engine import DATA


SETTINGS_PATH = DATA / "windows-settings.json"
MODIFIER_KEYS = {
    "Ctrl": (0x11,),
    "Alt": (0x12,),
    "Shift": (0x10,),
    "Windows": (0x5B, 0x5C),
}
SHORTCUT_KEYS = {
    "Space": 0x20,
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    **{str(number): ord(str(number)) for number in range(10)},
    **{f"F{number}": 0x6F + number for number in range(1, 25)},
}


@dataclass(frozen=True)
class ShortcutSettings:
    modifiers: tuple = ("Alt", "Windows")
    key: str | None = None
    enabled: bool = True

    def __post_init__(self):
        if (
            not isinstance(self.modifiers, tuple)
            or any(not isinstance(name, str) or name not in MODIFIER_KEYS for name in self.modifiers)
            or len(set(self.modifiers)) != len(self.modifiers)
            or (self.key is not None and (not isinstance(self.key, str) or self.key not in SHORTCUT_KEYS))
            or not isinstance(self.enabled, bool)
        ):
            raise ValueError("Choose a valid keyboard shortcut.")
        if self.key is None and len(self.modifiers) < 2:
            raise ValueError("Choose at least two modifiers, or add a key.")
        if self.key is not None and not self.modifiers and SHORTCUT_KEYS[self.key] < 0x70:
            raise ValueError("Add a modifier so normal typing does not start dictation.")
        if (self.modifiers == ("Alt",) and self.key == "F4") or ("Windows" in self.modifiers and self.key == "L"):
            raise ValueError("That shortcut is reserved by Windows. Choose another combination.")

    @property
    def label(self):
        parts = [name for name in MODIFIER_KEYS if name in self.modifiers]
        if self.key:
            parts.append(self.key)
        return " + ".join(parts)


def load_settings(path=SETTINGS_PATH):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Settings must be an object.")
        settings = ShortcutSettings(tuple(data["modifiers"]), data["key"], data["enabled"])
    except FileNotFoundError:
        return ShortcutSettings(), None
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return ShortcutSettings(), "Could not read saved settings. Using Alt + Windows; open Settings to save your shortcut."
    return settings, None


def save_settings(settings, path=SETTINGS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
            temporary = output.name
            json.dump(asdict(settings), output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
