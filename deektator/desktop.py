import os
import shutil
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk

from .engine import APP_ID, MAX_SECONDS, RELEASE_TAIL_MS, DictationError, Recording, microphone_sources
from .indicator import RecordingIndicator
from .shortcuts import KeyboardShortcut, PortalShortcut


CSS = b"""
window { background: #f0f8f6; color: #142e2b; }
.heading { font-weight: 800; font-size: 29pt; }
.subtitle, .hint { color: #405955; font-size: 11pt; }
.card { background: #ffffff; border: 1px solid #c7dbd6; border-radius: 16px; padding: 20px; }
.card-title { color: #142e2b; font-size: 13pt; font-weight: 700; }
.status { color: #17675b; font-size: 12pt; font-weight: 700; }
.recording, .error { color: #9c332d; }
.timer { color: #405955; font-feature-settings: "tnum"; }
button { border-radius: 9px; min-height: 34px; padding: 4px 14px; font-weight: 700; }
button.suggested-action { background: #12695c; color: #ffffff; }
button.suggested-action:hover { background: #0e554b; }
button.destructive-action { background: #9c332d; color: #ffffff; }
button:focus-visible { outline: 2px solid #13786b; outline-offset: 2px; }
.transcript { background: #f6faf9; border: 1px solid #dfebe8; border-radius: 8px; }
textview, textview text { background: transparent; color: #142e2b; font-size: 12pt; }
"""


def label(text, style=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True)
    if style:
        widget.add_css_class(style)
    return widget


def row(*children):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    for child in children:
        box.append(child)
    return box


class Desktop(Gtk.Application):
    def __init__(self, args, engine):
        super().__init__(application_id=APP_ID)
        self.args = args
        self.engine = engine
        self.recording = None
        self.record_source = None
        self.started = None
        self.timer = None
        self.release_timer = None
        self.microphone_ready = False
        self.processing = False
        self.cancel = threading.Event()
        self.shortcut = None
        self.sources = [args.source]
        self.downloading_model = False
        self.last_text = ""
        self.stopping = False

    def do_activate(self):
        if self.props.active_window:
            self.props.active_window.present()
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        window = Gtk.ApplicationWindow(application=self, title="Deektator")
        window.set_default_size(600, 590)
        window.set_size_request(415, 470)
        window.connect("close-request", self.on_close)

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for edge in ("top", "bottom", "start", "end"):
            layout.set_property("margin-" + edge, 24)
        window.set_child(layout)

        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading.append(label("Deektator", "heading"))
        heading.append(label("Local voice dictation", "subtitle"))
        layout.append(heading)

        capture = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        capture.add_css_class("card")
        self.status = label("Ready to record", "status")
        self.status.set_hexpand(True)
        self.duration = label("", "timer")
        capture.append(row(self.status, self.duration))
        self.detail = label("Start a recording to dictate with your microphone.", "hint")
        capture.append(self.detail)

        self.microphones = Gtk.DropDown.new_from_strings(
            [self.args.source or "System default microphone"]
        )
        self.microphones.set_hexpand(True)
        microphone_label = label("Microphone")
        microphone_label.set_mnemonic_widget(self.microphones)
        capture.append(row(microphone_label, self.microphones))
        self.level = Gtk.LevelBar(min_value=0, max_value=1)
        self.level.update_property([Gtk.AccessibleProperty.LABEL], ["Microphone input level"])
        capture.append(self.level)

        self.record_button = Gtk.Button(label="Start recording")
        self.record_button.add_css_class("suggested-action")
        self.record_button.connect("clicked", self.toggle_recording)
        self.shortcut_button = Gtk.Button(label="Enable shortcut")
        self.shortcut_button.connect("clicked", self.on_shortcut_button)
        capture.append(row(self.record_button, self.shortcut_button))
        self.shortcut_label = label("Global shortcut is off.", "hint")
        capture.append(self.shortcut_label)
        self.model_label = label("", "hint")
        self.model_label.set_hexpand(True)
        self.model_button = Gtk.Button(label="Download Small")
        self.model_button.connect("clicked", self.download_model)
        capture.append(row(self.model_label, self.model_button))
        layout.append(capture)

        transcript = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, vexpand=True)
        transcript.add_css_class("card")
        transcript_title = label("Latest transcript", "card-title")
        transcript_title.set_hexpand(True)
        self.copy_button = Gtk.Button(label="Copy")
        self.copy_button.set_sensitive(False)
        self.copy_button.connect("clicked", lambda _: self.copy_latest())
        transcript.append(row(transcript_title, self.copy_button))

        scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=70)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add_css_class("transcript")
        self.preview = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for edge in ("top", "bottom", "left", "right"):
            self.preview.set_property(edge + "-margin", 12)
        self.preview.get_buffer().set_text("Your transcript will appear here.")
        scroll.set_child(self.preview)
        transcript.append(scroll)
        layout.append(transcript)

        self.refresh_model_status()
        self.indicator = RecordingIndicator()
        threading.Thread(target=self.discover_microphones, daemon=True).start()
        window.present()
        if not self.args.manual:
            GLib.idle_add(self.connect_shortcut)

    def update_status(self, title, detail, style=None):
        self.status.set_text(title)
        self.detail.set_text(detail)
        for css in ("recording", "error"):
            if css == style:
                self.status.add_css_class(css)
            else:
                self.status.remove_css_class(css)

    def shortcut_status(self, description, ready):
        self.shortcut_label.set_text(f"Hold {description} · release to transcribe" if ready else description)
        waiting = isinstance(self.shortcut, PortalShortcut) and bool(self.shortcut.pending)
        can_configure = isinstance(self.shortcut, PortalShortcut) and bool(self.shortcut.session) and not waiting
        self.shortcut_button.set_visible(not ready or can_configure)
        self.shortcut_button.set_sensitive(not waiting)
        self.shortcut_button.set_label("Shortcut Settings" if can_configure else "Retry shortcut")

    def on_shortcut_button(self, _button):
        if isinstance(self.shortcut, PortalShortcut) and self.shortcut.session and not self.shortcut.pending:
            self.shortcut.configure()
        else:
            self.connect_shortcut()

    def connect_shortcut(self):
        if self.shortcut:
            self.shortcut.close()
        self.shortcut_button.set_sensitive(False)
        self.shortcut_label.set_text("Connecting to the global shortcut…")
        if self.args.keyboard:
            try:
                self.shortcut = KeyboardShortcut(self.args.keyboard, self.shortcut_changed, self.shortcut_status)
                return GLib.SOURCE_REMOVE
            except OSError as error:
                self.shortcut_status(f"Keyboard unavailable. {error.strerror}", False)
                return GLib.SOURCE_REMOVE
        self.shortcut = PortalShortcut(self.shortcut_changed, self.shortcut_status)
        self.shortcut.connect()
        return GLib.SOURCE_REMOVE

    def discover_microphones(self):
        try:
            sources, default = microphone_sources()
        except (OSError, ValueError, subprocess.SubprocessError):
            return
        GLib.idle_add(self.show_microphones, sources, default)

    def show_microphones(self, sources, default):
        if self.stopping:
            return GLib.SOURCE_REMOVE
        names = [name for name, _ in sources]
        labels = [description for _, description in sources]
        default_label = "System default microphone"
        if default in names:
            default_label = f"Default · {labels[names.index(default)]}"
        if self.args.source and self.args.source not in names:
            names.insert(0, self.args.source)
            labels.insert(0, self.args.source)
        selected = self.args.source
        if not selected and names and default and default not in names:
            selected = names[0]
        self.sources = [None, *names]
        self.microphones.set_model(Gtk.StringList.new([default_label, *labels]))
        self.microphones.set_selected(self.sources.index(selected))
        return GLib.SOURCE_REMOVE

    def refresh_model_status(self, error=None):
        active_model = self.engine.model
        self.model_label.set_text(error or (
            f"Model · {active_model.name}" if active_model.is_file() else "Download a local speech model."
        ))
        small_available = active_model.name == self.engine.small_model and active_model.is_file()
        self.model_button.set_visible(not self.args.model and not small_available)
        self.model_button.set_sensitive(not self.downloading_model)

    def download_model(self, _button):
        self.downloading_model = True
        self.model_button.set_sensitive(False)
        self.model_label.set_text("Downloading Whisper Small · 190 MB…")

        def download():
            error = None
            try:
                self.engine.download_model(self.cancel)
            except (OSError, DictationError) as problem:
                error = f"Could not download Whisper Small. {problem}"
            GLib.idle_add(self.model_downloaded, error)

        threading.Thread(target=download, name="model-download").start()

    def model_downloaded(self, error):
        if not self.stopping:
            self.downloading_model = False
            self.refresh_model_status(error)
        return GLib.SOURCE_REMOVE

    def shortcut_changed(self, down):
        if down:
            self.start_recording("shortcut")
        elif self.record_source == "shortcut" and self.release_timer is None:
            self.release_timer = GLib.timeout_add(RELEASE_TAIL_MS, self.release_shortcut)

    def release_shortcut(self):
        self.release_timer = None
        self.finish_recording()
        return GLib.SOURCE_REMOVE

    def toggle_recording(self, _button):
        if self.recording is None:
            self.start_recording("button")
        else:
            self.finish_recording()

    def start_recording(self, source):
        if self.recording or self.processing or self.stopping:
            return
        try:
            self.engine.validate()
            selected = self.microphones.get_selected()
            microphone = self.sources[selected] if selected < len(self.sources) else self.args.source
            self.recording = Recording(microphone)
        except (OSError, DictationError) as error:
            self.update_status("Could not start recording", str(error), "error")
            self.notify("Recording could not start", source)
            return
        self.record_source = source
        self.microphone_ready = False
        self.started = time.monotonic()
        self.duration.set_text("0:00")
        self.level.set_value(0)
        self.microphones.set_sensitive(False)
        self.update_status("Opening microphone…", "Wait for the recording indicator before speaking.")
        self.record_button.set_label("Stop recording")
        self.record_button.remove_css_class("suggested-action")
        self.record_button.add_css_class("destructive-action")
        self.timer = GLib.timeout_add(50, self.update_recording)

    def update_recording(self):
        elapsed = int(time.monotonic() - self.started)
        self.duration.set_text(f"{elapsed // 60}:{elapsed % 60:02}")
        if (
            elapsed >= MAX_SECONDS or self.recording.process.poll() is not None
            or (elapsed >= 3 and not self.microphone_ready)
        ):
            self.timer = None
            self.finish_recording()
            return GLib.SOURCE_REMOVE
        level = self.recording.input_level()
        if level is not None:
            self.level.set_value(level)
            if not self.microphone_ready:
                self.microphone_ready = True
                self.update_status(
                    "Recording",
                    "Release the shortcut to transcribe." if self.record_source == "shortcut" else "Stop after speaking.",
                    "recording",
                )
                if not self.indicator.show(True):
                    self.notify("Recording", self.record_source)
        return GLib.SOURCE_CONTINUE

    def finish_recording(self):
        if self.recording is None:
            return
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.release_timer is not None:
            GLib.source_remove(self.release_timer)
            self.release_timer = None
        recording, self.recording = self.recording, None
        source, self.record_source = self.record_source, None
        recording.stop()
        self.indicator.show(False)
        self.processing = True
        self.record_button.set_sensitive(False)
        self.record_button.set_label("Start recording")
        self.record_button.remove_css_class("destructive-action")
        self.record_button.add_css_class("suggested-action")
        self.update_status("Transcribing…", "Whisper is processing the recording on this device.")
        threading.Thread(target=self.transcribe, args=(recording, source), name="transcription").start()

    def transcribe(self, recording, source):
        text, error = "", None
        try:
            audio = recording.to_wav()
            if audio and not self.cancel.is_set():
                text = self.engine.transcribe(audio, self.cancel)
        except (DictationError, OSError, UnicodeError) as problem:
            error = str(problem)
        finally:
            recording.close()
        GLib.idle_add(self.transcribed, text, error, source)

    def transcribed(self, text, error, source):
        if self.stopping:
            return GLib.SOURCE_REMOVE
        self.processing = False
        self.record_button.set_sensitive(True)
        self.microphones.set_sensitive(True)
        self.level.set_value(0)
        if error:
            self.update_status("Dictation failed", error, "error")
            self.notify("Dictation failed", source)
        elif not text:
            self.update_status("No speech detected", "Try speaking closer to the microphone.")
            self.notify("No speech detected", source)
        else:
            self.last_text = text
            self.preview.get_buffer().set_text(text)
            self.copy_button.set_sensitive(True)
            self.copy_latest(source)
        return GLib.SOURCE_REMOVE

    def copy_latest(self, source=None):
        try:
            if os.environ.get("WAYLAND_DISPLAY"):
                subprocess.run(
                    ["wl-copy", "--type", "text/plain;charset=utf-8"], input=self.last_text.encode("utf-8"),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=True,
                )
            else:
                content = Gdk.ContentProvider.new_for_value(GObject.Value(str, self.last_text))
                if not self.preview.get_clipboard().set_content(content):
                    raise DictationError("The desktop refused the clipboard content.")
        except (OSError, subprocess.SubprocessError, DictationError):
            self.update_status("Clipboard unavailable", "You can select and copy the text below.", "error")
            self.notify("Transcript ready in Deektator", source)
        else:
            self.update_status("Copied to clipboard", "Paste the transcript wherever you need it.")
            self.notify("Transcript copied to clipboard", source)

    def notify(self, message, source):
        if source == "shortcut" and shutil.which("notify-send"):
            try:
                subprocess.Popen(
                    ["notify-send", "--app-name=Deektator", "Deektator", message],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError:
                pass

    def on_close(self, _window):
        self.stopping = True
        self.cancel.set()
        if self.shortcut:
            self.shortcut.close()
        if self.timer is not None:
            GLib.source_remove(self.timer)
        if self.release_timer is not None:
            GLib.source_remove(self.release_timer)
        if self.recording:
            self.recording.close()
        self.indicator.close()
        return False
