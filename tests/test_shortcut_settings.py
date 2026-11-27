import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deektator.settings import ShortcutSettings, load_settings, save_settings
from deektator.win32 import DictationChord


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        self.keys = set()

    def poll(self, chord, *keys):
        self.keys = set(keys)
        return chord.poll()

    def chord(self, settings=None):
        return DictationChord(lambda key: key in self.keys, settings)

    def test_default_requires_release_before_first_recording(self):
        chord = self.chord()
        self.assertIsNone(self.poll(chord, 0x12, 0x5B))
        self.assertIsNone(self.poll(chord))
        self.assertIs(self.poll(chord, 0x12, 0x5B), True)
        self.assertIsNone(self.poll(chord, 0x12, 0x5B))
        self.assertIs(self.poll(chord), False)
        self.assertIs(self.poll(chord, 0x12, 0x5C), True)

    def test_release_any_required_key_stops_and_requires_full_release(self):
        chord = self.chord(ShortcutSettings(("Ctrl", "Alt"), "Space"))
        self.poll(chord)
        self.assertIs(self.poll(chord, 0x11, 0x12, 0x20), True)
        self.assertIs(self.poll(chord, 0x11, 0x12), False)
        self.assertIsNone(self.poll(chord, 0x11, 0x12, 0x20))
        self.poll(chord)
        self.assertIs(self.poll(chord, 0x11, 0x12, 0x20), True)
        self.assertIs(self.poll(chord, 0x12, 0x20), False)

    def test_unrelated_modifiers_do_not_start_dictation(self):
        chord = self.chord()
        self.poll(chord)
        self.assertIsNone(self.poll(chord, 0x11, 0x12, 0x5B))
        self.assertIsNone(self.poll(chord, 0x10, 0x12, 0x5B))

    def test_reset_after_settings_waits_for_keys_to_be_released(self):
        chord = self.chord()
        self.poll(chord)
        chord.reset()
        self.assertIsNone(self.poll(chord, 0x12, 0x5B))
        self.poll(chord)
        self.assertIs(self.poll(chord, 0x12, 0x5B), True)

    def test_function_key_can_be_used_alone(self):
        chord = self.chord(ShortcutSettings((), "F8"))
        self.poll(chord)
        self.assertIs(self.poll(chord, 0x77), True)
        self.assertIs(self.poll(chord), False)

    def test_disabled_shortcut_does_not_record(self):
        chord = self.chord(ShortcutSettings(enabled=False))
        self.poll(chord)
        self.assertIsNone(self.poll(chord, 0x12, 0x5B))


class SettingsTests(unittest.TestCase):
    def test_rejects_accidental_typing_and_reserved_combinations(self):
        for modifiers, key in [((), "A"), ((), "F"), ((), "Space"), (("Alt",), None), (("Windows",), "L"), (("Alt",), "F4")]:
            with self.subTest(modifiers=modifiers, key=key), self.assertRaises(ValueError):
                ShortcutSettings(modifiers, key)

    def test_preferences_survive_a_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences" / "settings.json"
            self.assertEqual(load_settings(path), (ShortcutSettings(), None))
            for settings in [ShortcutSettings(("Ctrl", "Alt"), "Space"), ShortcutSettings(enabled=False)]:
                save_settings(settings, path)
                self.assertEqual(load_settings(path), (settings, None))

    def test_bad_settings_fall_back_to_default_with_explanation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for content in ["broken", "[]", "{}", json.dumps({"modifiers": None, "key": "Q", "enabled": True}),
                            json.dumps({"modifiers": ["Alt"], "key": ["Q"], "enabled": True}),
                            json.dumps({"modifiers": ["Alt", "Windows"], "key": None, "enabled": "false"})]:
                path.write_text(content, encoding="utf-8")
                settings, error = load_settings(path)
                self.assertEqual(settings, ShortcutSettings())
                self.assertTrue(error)

    def test_failed_save_keeps_previous_preferences_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(ShortcutSettings(), path)
            with patch("deektator.settings.os.replace", side_effect=PermissionError("Read only")):
                with self.assertRaises(OSError):
                    save_settings(ShortcutSettings(("Ctrl",), "Space"), path)
            self.assertEqual(load_settings(path), (ShortcutSettings(), None))
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
