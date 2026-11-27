import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deektator.settings import ShortcutSettings, load_settings, save_settings


@unittest.skipUnless(sys.platform == "win32", "Windows desktop integration")
class WindowsSettingsTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from deektator.windows import Desktop

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings.json"
        for target, replacement in [
            ("deektator.windows.load_settings", lambda: load_settings(self.path)),
            ("deektator.windows.save_settings", lambda settings: save_settings(settings, self.path)),
            ("deektator.windows.microphones", lambda _audio: ([(0, "Test microphone")], 0)),
        ]:
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.api = Mock()
        self.api.key_down.return_value = False
        self.args = SimpleNamespace(manual=False, source=None, model=None)
        self.engine = SimpleNamespace(model=self.path.parent / "model.bin", small_model="model.bin")
        self.app = Desktop(self.root, self.api, self.args, self.engine)
        self.addCleanup(lambda: self.app.close())
        self.root.update()

    def choose_ctrl_space(self, dialog):
        for name, variable in dialog.modifiers.items():
            variable.set(name == "Ctrl")
        dialog.key.set("Space")
        dialog.refresh()

    def test_save_updates_main_window_and_persists_for_next_launch(self):
        self.app.settings_button.invoke()
        dialog = self.app.settings_dialog
        self.choose_ctrl_space(dialog)
        dialog.save_button.invoke()
        self.assertIsNone(self.app.settings_dialog)
        self.assertIn("Ctrl + Space", self.app.shortcut_text.get())
        self.assertEqual(self.app.chord.settings, load_settings(self.path)[0])
        self.assertFalse(self.app.chord.armed)

    def test_cancel_keeps_current_shortcut(self):
        self.app.open_settings()
        self.choose_ctrl_space(self.app.settings_dialog)
        self.app.settings_dialog.close()
        self.assertEqual(self.app.settings, ShortcutSettings())
        self.assertFalse(self.path.exists())

    def test_shortcut_is_suspended_while_dialog_is_open(self):
        self.app.open_settings()
        with patch.object(self.app.chord, "poll") as poll:
            self.root.after_cancel(self.app.poll_job)
            self.app.poll()
            poll.assert_not_called()

    def test_disable_and_restore_default(self):
        self.app.open_settings()
        dialog = self.app.settings_dialog
        dialog.enabled.set(False)
        dialog.refresh()
        dialog.save()
        self.assertIsNone(self.app.chord)
        self.assertFalse(load_settings(self.path)[0].enabled)
        self.app.open_settings()
        self.app.settings_dialog.restore_default()
        self.app.settings_dialog.save()
        self.assertEqual(self.app.settings, ShortcutSettings())
        self.assertIsNotNone(self.app.chord)

    def test_failed_save_keeps_dialog_open_and_old_shortcut_active(self):
        self.app.open_settings()
        dialog = self.app.settings_dialog
        self.choose_ctrl_space(dialog)
        with patch("deektator.windows.save_settings", side_effect=PermissionError("Read only")):
            dialog.save()
        self.assertIs(self.app.settings_dialog, dialog)
        self.assertIn("Could not save", dialog.error.get())
        self.assertEqual(self.app.settings, ShortcutSettings())

    def test_manual_launch_overrides_preference_without_overwriting_it(self):
        from deektator.windows import Desktop

        save_settings(ShortcutSettings(), self.path)
        self.app.close()
        import tkinter as tk
        self.root = tk.Tk()
        self.args.manual = True
        self.app = Desktop(self.root, self.api, self.args, self.engine)
        self.assertIsNone(self.app.chord)
        self.assertTrue(load_settings(self.path)[0].enabled)


if __name__ == "__main__":
    unittest.main()
