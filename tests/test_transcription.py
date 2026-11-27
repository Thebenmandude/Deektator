import argparse
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from deektator.__main__ import positive_integer
from deektator.engine import DictationError, Whisper, transcription_threads


class TranscriptionTests(unittest.TestCase):
    def test_automatic_thread_budget_scales_and_leaves_headroom(self):
        for cores, expected in [(None, 1), (1, 1), (2, 2), (4, 4), (8, 6), (20, 16), (64, 16)]:
            with self.subTest(cores=cores), patch("deektator.engine.os.cpu_count", return_value=cores):
                self.assertEqual(transcription_threads(), expected)

    def test_manual_thread_override_and_invalid_values(self):
        self.assertEqual(Whisper("whisper-cli", None, "en", True, threads=3).threads, 3)
        for value in [0, -1, True, 2.5, "four"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Whisper("whisper-cli", None, "en", True, threads=value)
        for value in ["0", "-4", "eight", "1.5"]:
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                positive_integer(value)

    def test_windows_optimization_is_probed_once_and_only_when_supported(self):
        for help_text, expected in [(b"options: --no-flash-attn", ["-nfa"]), (b"older runtime", [])]:
            with self.subTest(help_text=help_text), patch.object(sys, "platform", "win32"):
                engine = Whisper("whisper-cli", None, "en", True)
                with patch("deektator.engine.subprocess.run", return_value=Mock(returncode=0, stdout=help_text)) as run:
                    self.assertEqual(engine.cpu_flags(), expected)
                    self.assertEqual(engine.cpu_flags(), expected)
                    run.assert_called_once()

    def test_failed_probe_keeps_compatible_options(self):
        for error in [OSError("Unavailable"), subprocess.TimeoutExpired("whisper-cli", 3)]:
            with self.subTest(error=error), patch.object(sys, "platform", "win32"):
                engine = Whisper("whisper-cli", None, "en", True)
                with patch("deektator.engine.subprocess.run", side_effect=error):
                    self.assertEqual(engine.cpu_flags(), [])

    def test_linux_keeps_existing_attention_behavior(self):
        with patch.object(sys, "platform", "linux"), patch("deektator.engine.subprocess.run") as run:
            self.assertEqual(Whisper("whisper-cli", None, "en", True).cpu_flags(), [])
            run.assert_not_called()

    def test_transcription_uses_selected_threads_and_keeps_model_and_text_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "small.en.bin"
            model.touch()
            engine = Whisper("whisper-cli", model, "en", True, threads=12)
            engine._cpu_flags = ["-nfa"]
            process = Mock(returncode=0)
            process.communicate.return_value = (None, b"")

            def start(command, **kwargs):
                self.assertEqual(command[command.index("-t") + 1], "12")
                self.assertEqual(command[command.index("-m") + 1], str(model))
                self.assertIn("-nfa", command)
                output = Path(command[command.index("-of") + 1]).with_suffix(".txt")
                output.write_text("um, this works.", encoding="utf-8")
                context = Mock()
                context.__enter__ = Mock(return_value=process)
                context.__exit__ = Mock(return_value=False)
                return context

            with patch("deektator.engine.shutil.which", return_value="whisper-cli"), patch(
                "deektator.engine.subprocess.Popen", side_effect=start,
            ):
                self.assertEqual(engine.transcribe(Path(folder) / "audio.wav"), "This works.")
                cancel = threading.Event()
                cancel.set()
                with self.assertRaisesRegex(DictationError, "cancelled"):
                    engine.transcribe(Path(folder) / "audio.wav", cancel)
                process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
