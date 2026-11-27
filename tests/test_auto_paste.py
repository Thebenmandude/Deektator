import sys
import ctypes
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform == "win32", "Windows desktop integration")
class AutoPasteTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from deektator.windows import Desktop

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        model = Path(self.directory.name) / "model.bin"
        model.touch()
        audio_patch = patch("deektator.windows.microphones", return_value=([(0, "Test microphone")], 0))
        audio_patch.start()
        self.addCleanup(audio_patch.stop)
        recording_patch = patch("deektator.windows.WindowsRecording")
        recording = recording_patch.start()
        recording.return_value.input_level.return_value = None
        recording.return_value.worker.is_alive.return_value = True
        self.addCleanup(recording_patch.stop)
        self.root = tk.Tk()
        self.api = Mock()
        self.api.key_down.return_value = False
        self.api.paste.return_value = True
        engine = SimpleNamespace(model=model, small_model="model.bin", validate=Mock())
        self.app = Desktop(self.root, self.api, SimpleNamespace(manual=False, source=None, model=None), engine)
        self.addCleanup(self.app.close)
        self.root.update()

    def run_pending_paste(self):
        time.sleep(0.04)
        self.root.update()

    def test_shortcut_recording_sends_paste_after_new_text_is_copied(self):
        self.app.engine.validate()
        self.app.start("shortcut")
        self.assertTrue(self.app.paste_requested)
        self.app.transcribed("hello there")
        self.assertEqual(self.root.clipboard_get(), "hello there")
        self.api.paste.assert_not_called()
        self.run_pending_paste()
        self.api.paste.assert_called_once_with()
        self.assertFalse(self.app.paste_requested)

    def test_button_recording_also_pastes_after_new_text_is_copied(self):
        self.app.start("button")
        self.app.transcribed("hello there")
        self.run_pending_paste()
        self.api.paste.assert_called_once_with()
        self.assertEqual(self.root.clipboard_get(), "hello there")

    def test_copying_an_existing_transcript_does_not_paste(self):
        self.app.transcribed("hello there")
        self.run_pending_paste()
        self.api.paste.assert_not_called()

    def test_failed_paste_leaves_transcript_available(self):
        self.app.paste_requested = True
        self.api.paste.return_value = False
        self.app.transcribed("hello there")
        self.run_pending_paste()
        self.assertIn("Paste command failed", self.app.status.get())
        self.assertEqual(self.root.clipboard_get(), "hello there")

    def test_stale_clipboard_never_triggers_paste(self):
        self.app.paste_requested = True
        self.app.transcribed("new text")
        self.root.clipboard_clear()
        self.root.clipboard_append("older or replaced text")
        self.run_pending_paste()
        self.api.paste.assert_not_called()

    def test_failed_transcription_does_not_paste(self):
        self.app.paste_requested = True
        self.app.transcribed(OSError("failed"))
        self.api.paste.assert_not_called()
        self.assertFalse(self.app.paste_requested)

    def test_send_input_structure_matches_windows_size(self):
        from deektator.win32 import Input

        self.assertEqual(ctypes.sizeof(Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_processing_indicator_remains_until_paste_is_sent(self):
        self.app.indicator = Mock(window=123)
        self.app.processing = True
        self.app.show_transcribing()
        self.app.indicator.set_text.assert_called_with("Transcribing.")
        self.app.animate_indicator()
        self.app.indicator.set_text.assert_called_with("Transcribing..")
        self.app.paste_requested = True
        self.app.transcribed("hello there")
        self.app.indicator.close.assert_not_called()
        self.run_pending_paste()
        self.api.paste.assert_called_once()
        self.app.indicator.close.assert_called_once()
        self.assertIsNone(self.app.indicator_job)

    def test_processing_indicator_closes_when_transcription_fails(self):
        self.app.indicator = Mock(window=123)
        self.app.processing = True
        self.app.show_transcribing()
        self.app.transcribed(OSError("failed"))
        self.app.indicator.close.assert_called_once()
        self.assertIsNone(self.app.indicator_job)


if __name__ == "__main__":
    unittest.main()
