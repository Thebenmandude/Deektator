"""Windows desktop interface for Deektator."""

import queue
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import ttk

import sounddevice

from .engine import MAX_SECONDS, RELEASE_TAIL_MS, DictationError
from .settings import load_settings, save_settings
from .win32 import DesktopAPI, DictationChord, RecordingIndicator
from .windows_audio import WindowsRecording, microphones
from .windows_settings import SettingsDialog


class Desktop:
    def __init__(self, root, api, args, engine):
        self.root = root
        self.engine = engine
        self.args = args
        self.api = api
        self.indicator = RecordingIndicator(api)
        self.settings, settings_error = load_settings()
        if args.manual:
            self.settings = replace(self.settings, enabled=False)
        self.chord = DictationChord(api.key_down, self.settings) if self.settings.enabled else None
        self.settings_dialog = None
        self.cancel = threading.Event()
        self.tasks = queue.SimpleQueue()
        self.recording = None
        self.record_source = None
        self.paste_requested = False
        self.release_job = None
        self.poll_job = None
        self.indicator_job = None
        self.paste_job = None
        self.indicator_frame = 0
        self.processing = False
        self.last_text = ""
        self.indicator_error = False
        self.devices = []

        root.title("Deektator")
        root.minsize(410, 440)
        root.geometry("550x540")
        root.protocol("WM_DELETE_WINDOW", self.close)
        main = ttk.Frame(root, padding=20)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        heading = ttk.Frame(main)
        heading.grid(sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="Deektator", font=("Segoe UI", 20, "bold")).grid(row=0, column=0, sticky="w")
        self.settings_button = ttk.Button(heading, text="Settings", command=self.open_settings)
        self.settings_button.grid(row=0, column=1, sticky="e")
        self.shortcut_text = tk.StringVar()
        self.refresh_shortcut()
        ttk.Label(main, textvariable=self.shortcut_text, wraplength=375).grid(sticky="w", pady=(2, 12))

        capture = ttk.LabelFrame(main, text="Microphone", padding=12)
        capture.grid(sticky="ew")
        capture.columnconfigure(0, weight=1)
        self.inputs = ttk.Combobox(capture, state="readonly")
        self.inputs.grid(sticky="ew")
        self.level = ttk.Progressbar(capture, mode="determinate", maximum=1)
        self.level.grid(sticky="ew", pady=(8, 10))
        self.status = tk.StringVar(value="Ready to record.")
        ttk.Label(capture, textvariable=self.status, wraplength=360).grid(sticky="w")
        self.record_button = ttk.Button(capture, text="Start recording", command=self.toggle_recording)
        self.record_button.grid(sticky="w", pady=(8, 0))

        transcript = ttk.LabelFrame(main, text="Latest transcript", padding=12)
        transcript.grid(sticky="nsew", pady=12)
        transcript.columnconfigure(0, weight=1)
        transcript.rowconfigure(0, weight=1)
        self.preview = tk.Text(transcript, wrap="word", height=4, state="disabled", padx=8, pady=8)
        self.preview.grid(sticky="nsew")
        scrollbar = ttk.Scrollbar(transcript, orient="vertical", command=self.preview.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.preview.configure(yscrollcommand=scrollbar.set)
        self.copy_button = ttk.Button(transcript, text="Copy transcript", command=self.copy_latest, state="disabled")
        self.copy_button.grid(sticky="w", pady=(8, 0))

        footer = ttk.Frame(main)
        footer.grid(sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.model_status = tk.StringVar()
        ttk.Label(footer, textvariable=self.model_status, wraplength=295).grid(sticky="w")
        self.download_button = ttk.Button(footer, text="Download Small", command=self.download_model)
        self.download_button.grid(row=0, column=1, padx=(8, 0))
        self.refresh_model()
        self.load_devices()
        if settings_error:
            self.status.set(settings_error)
        self.poll()

    def refresh_shortcut(self):
        self.shortcut_text.set(
            f"Hold {self.settings.label} while speaking. Release to insert in the selected text box."
            if self.chord else "Global shortcut is off. Enable it in Settings."
        )

    def open_settings(self):
        if self.recording or self.processing:
            return
        if self.settings_dialog:
            self.settings_dialog.lift()
            return
        if self.chord:
            self.chord.reset()
        self.settings_dialog = SettingsDialog(self.root, self.settings, self.apply_settings, self.settings_closed)

    def apply_settings(self, settings):
        save_settings(settings)
        self.settings = settings
        self.chord = DictationChord(self.api.key_down, settings) if settings.enabled else None
        self.refresh_shortcut()
        self.status.set("Settings saved.")

    def settings_closed(self):
        self.settings_dialog = None
        if self.chord:
            self.chord.reset()
        self.settings_button.focus_set()

    def load_devices(self):
        try:
            self.devices, default = microphones(sounddevice)
        except (OSError, ValueError, sounddevice.PortAudioError) as error:
            self.status.set(f"Could not list microphones. {error}")
            return
        self.inputs["values"] = [f"{name} ({index})" for index, name in self.devices]
        selection = next(
            (position for position, (index, name) in enumerate(self.devices) if self.args.source in (str(index), name)),
            None,
        )
        if selection is None:
            selection = next((position for position, (index, _) in enumerate(self.devices) if index == default), None)
        if selection is not None:
            self.inputs.current(selection)
        else:
            self.status.set("No microphones found. Connect a microphone and restart Deektator.")
        if self.args.source and all(self.args.source not in (str(index), name) for index, name in self.devices):
            self.status.set(f"Microphone {self.args.source} was not found. Check the selected input.")

    def poll(self):
        if self.chord and self.settings_dialog is None:
            transition = self.chord.poll()
            if transition is True:
                self.start("shortcut")
            elif transition is False and self.record_source == "shortcut" and self.release_job is None:
                self.release_job = self.root.after(RELEASE_TAIL_MS, self.finish)

        if self.recording:
            elapsed = time.monotonic() - self.started
            level = self.recording.input_level()
            if level is not None:
                self.level["value"] = level
                if not self.indicator_error and not self.indicator.window:
                    try:
                        self.indicator.show()
                    except OSError:
                        self.indicator_error = True
                status = f"Recording · {int(elapsed) // 60}:{int(elapsed) % 60:02}"
                if self.indicator_error:
                    status += " · Desktop indicator unavailable"
                self.status.set(status)
            if not self.recording.worker.is_alive() or elapsed >= MAX_SECONDS or (level is None and elapsed >= 4):
                self.finish()

        while not self.tasks.empty():
            kind, result = self.tasks.get()
            if kind == "model":
                self.refresh_model(result)
            else:
                self.transcribed(result)
        self.poll_job = self.root.after(25, self.poll)

    def toggle_recording(self):
        if self.recording:
            self.finish()
        else:
            self.start("button")

    def start(self, source):
        if self.processing or self.recording or self.settings_dialog is not None:
            return
        self.dismiss_indicator()
        selection = self.inputs.current()
        if selection < 0:
            self.status.set("Choose a microphone before recording.")
            return
        try:
            self.engine.validate()
        except DictationError as error:
            self.status.set(str(error))
            return
        self.record_source = source
        self.paste_requested = True
        self.started = time.monotonic()
        self.indicator_error = False
        self.recording = WindowsRecording(sounddevice, self.devices[selection][0])
        self.level["value"] = 0
        self.inputs.configure(state="disabled")
        self.settings_button.configure(state="disabled")
        self.record_button.configure(text="Stop recording")
        self.status.set("Opening microphone…")

    def finish(self):
        if self.release_job is not None:
            self.root.after_cancel(self.release_job)
            self.release_job = None
        if not self.recording:
            return
        recording, self.recording = self.recording, None
        self.record_source = None
        recording.stop.set()
        self.processing = True
        self.record_button.configure(text="Start recording", state="disabled")
        self.status.set("Transcribing locally…")
        self.show_transcribing()

        def transcribe():
            try:
                with tempfile.TemporaryDirectory(prefix="deektator-audio-") as folder:
                    audio = recording.to_wav(Path(folder) / "recording.wav")
                    result = self.engine.transcribe(audio, self.cancel) if audio and not self.cancel.is_set() else ""
            except (DictationError, OSError, UnicodeError) as error:
                result = error
            self.tasks.put(("transcript", result))

        threading.Thread(target=transcribe, name="transcription").start()

    def show_transcribing(self):
        if self.indicator_error:
            return
        try:
            if not self.indicator.window:
                self.indicator.show()
            self.indicator_frame = 0
            self.animate_indicator()
        except OSError:
            self.indicator_error = True
            self.dismiss_indicator()

    def animate_indicator(self):
        if not self.processing or not self.indicator.window:
            self.indicator_job = None
            return
        try:
            self.indicator.set_text("Transcribing" + "." * (1 + self.indicator_frame % 3))
        except OSError:
            self.indicator_error = True
            self.dismiss_indicator()
            return
        self.indicator_frame += 1
        self.indicator_job = self.root.after(320, self.animate_indicator)

    def dismiss_indicator(self):
        if self.indicator_job is not None:
            self.root.after_cancel(self.indicator_job)
            self.indicator_job = None
        self.indicator.close()

    def transcribed(self, result):
        if isinstance(result, Exception):
            self.paste_requested = False
            self.status.set(str(result))
            self.finish_processing()
        elif not result:
            self.paste_requested = False
            self.status.set("No speech detected. Check your microphone and try again.")
            self.finish_processing()
        else:
            self.last_text = result
            self.preview.configure(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", result)
            self.preview.configure(state="disabled")
            self.copy_button.configure(state="normal")
            copied = self.copy_latest()
            paste_requested, self.paste_requested = self.paste_requested, False
            if copied and paste_requested:
                # Let Tk publish the new clipboard contents before injecting the
                # paste shortcut into whichever app has keyboard focus.
                self.paste_job = self.root.after(25, lambda: self.paste_latest(result))
            else:
                self.finish_processing()

    def paste_latest(self, text):
        self.paste_job = None
        try:
            try:
                current = self.root.clipboard_get()
            except tk.TclError:
                current = None
            if current != text:
                self.status.set("Clipboard changed before pasting. Transcript is still available to copy here.")
            elif self.api.paste():
                self.status.set("Paste command sent.")
            else:
                self.status.set("Copied to clipboard. Paste command failed; press Ctrl + V.")
        finally:
            self.finish_processing()

    def finish_processing(self):
        self.processing = False
        self.record_button.configure(state="normal")
        self.inputs.configure(state="readonly")
        self.settings_button.configure(state="normal")
        self.level["value"] = 0
        self.dismiss_indicator()

    def copy_latest(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_text)
        except tk.TclError:
            self.status.set("Clipboard unavailable. Click Copy transcript to retry.")
            return False
        else:
            self.status.set("Copied to clipboard.")
            return True

    def refresh_model(self, error=None):
        model = self.engine.model
        self.model_status.set(error or (model.name if model.is_file() else "Download a local speech model."))
        if self.args.model or (model.name == self.engine.small_model and model.is_file()):
            self.download_button.grid_remove()
        else:
            self.download_button.configure(state="normal")

    def download_model(self):
        self.model_status.set("Downloading Whisper Small · 190 MB…")
        self.download_button.configure(state="disabled")

        def download():
            error = None
            try:
                self.engine.download_model(self.cancel)
            except (DictationError, OSError) as problem:
                error = f"Could not download Whisper Small. {problem}"
            self.tasks.put(("model", error))

        threading.Thread(target=download, name="model-download").start()

    def close(self):
        self.cancel.set()
        for job in (self.poll_job, self.release_job, self.paste_job):
            if job is not None:
                self.root.after_cancel(job)
        if self.recording:
            self.recording.stop.set()
        self.dismiss_indicator()
        self.root.destroy()


def run(args, engine):
    api = DesktopAPI()
    root = tk.Tk()
    Desktop(root, api, args, engine)
    root.mainloop()
    return 0
