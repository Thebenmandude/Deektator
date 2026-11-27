"""Windows desktop interface for Deektator."""

import queue
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import sounddevice

from .engine import MAX_SECONDS, RELEASE_TAIL_MS, DictationError
from .win32 import DesktopAPI, DictationChord, RecordingIndicator
from .windows_audio import WindowsRecording, microphones


class Desktop:
    def __init__(self, root, api, args, engine):
        self.root = root
        self.engine = engine
        self.args = args
        self.indicator = RecordingIndicator(api)
        self.chord = None if args.manual else DictationChord(api.key_down)
        self.cancel = threading.Event()
        self.tasks = queue.SimpleQueue()
        self.recording = None
        self.record_source = None
        self.release_job = None
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

        ttk.Label(main, text="Deektator", font=("Segoe UI", 20, "bold")).grid(sticky="w")
        shortcut = (
            "Hold Alt + Windows while speaking. Release to transcribe."
            if self.chord else "Global shortcut is off."
        )
        ttk.Label(main, text=shortcut, wraplength=375).grid(sticky="w", pady=(2, 12))

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
        self.poll()

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
        if self.chord:
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
        self.root.after(25, self.poll)

    def toggle_recording(self):
        if self.recording:
            self.finish()
        else:
            self.start("button")

    def start(self, source):
        if self.processing or self.recording:
            return
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
        self.started = time.monotonic()
        self.indicator_error = False
        self.recording = WindowsRecording(sounddevice, self.devices[selection][0])
        self.level["value"] = 0
        self.inputs.configure(state="disabled")
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
        self.indicator.close()
        self.processing = True
        self.record_button.configure(text="Start recording", state="disabled")
        self.status.set("Transcribing locally…")

        def transcribe():
            try:
                with tempfile.TemporaryDirectory(prefix="deektator-audio-") as folder:
                    audio = recording.to_wav(Path(folder) / "recording.wav")
                    result = self.engine.transcribe(audio, self.cancel) if audio and not self.cancel.is_set() else ""
            except (DictationError, OSError, UnicodeError) as error:
                result = error
            self.tasks.put(("transcript", result))

        threading.Thread(target=transcribe, name="transcription").start()

    def transcribed(self, result):
        self.processing = False
        self.record_button.configure(state="normal")
        self.inputs.configure(state="readonly")
        self.level["value"] = 0
        if isinstance(result, Exception):
            self.status.set(str(result))
        elif not result:
            self.status.set("No speech detected. Check your microphone and try again.")
        else:
            self.last_text = result
            self.preview.configure(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", result)
            self.preview.configure(state="disabled")
            self.copy_button.configure(state="normal")
            self.copy_latest()

    def copy_latest(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_text)
        except tk.TclError:
            self.status.set("Clipboard unavailable. Click Copy transcript to retry.")
        else:
            self.status.set("Copied to clipboard.")

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
        if self.recording:
            self.recording.stop.set()
        self.indicator.close()
        self.root.destroy()


def run(args, engine):
    api = DesktopAPI()
    root = tk.Tk()
    Desktop(root, api, args, engine)
    root.mainloop()
    return 0
