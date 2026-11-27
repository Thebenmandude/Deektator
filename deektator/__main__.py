import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .engine import APP_ID, DictationError, Whisper


def install_launcher(args, replace=True):
    from gi.repository import GLib

    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    launcher = data_home / "applications" / f"{APP_ID}.desktop"
    packaged_launcher = Path("/usr/share/applications") / launcher.name
    if not replace and (launcher.exists() or packaged_launcher.is_file()):
        return launcher
    executable = Path(__file__).resolve().parents[1] / "run-deektator"
    command = [str(executable)]
    if args.keyboard:
        command += ["--keyboard", str(args.keyboard.absolute())]
    if args.model:
        command += ["--model", str(args.model.absolute())]
    if args.whisper:
        binary = str(Path(args.whisper).absolute()) if "/" in args.whisper else args.whisper
        command += ["--whisper", binary]
    if args.language != "en":
        command += ["--language", args.language]
    if args.keep_fillers:
        command.append("--keep-fillers")
    if args.source:
        command += ["--source", args.source]
    # Escape each argument for the Exec field before writing the key file.
    quoted = []
    for argument in command:
        escaped = "".join(
            "\\" + char if char in '\\"$`' else "%%" if char == "%" else char for char in argument
        )
        quoted.append(f'"{escaped}"')
    entry = GLib.KeyFile()
    for key, value in {
        "Type": "Application",
        "Name": "Deektator",
        "Comment": "Offline voice dictation",
        "Exec": " ".join(quoted),
        "Icon": "audio-input-microphone",
        "Categories": "Utility;",
        "StartupWMClass": APP_ID,
    }.items():
        entry.set_string("Desktop Entry", key, value)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    entry.save_to_file(str(launcher))
    return launcher


def main():
    windows = sys.platform == "win32"
    parser = argparse.ArgumentParser(description="Offline desktop dictation.")
    parser.add_argument("--version", action="version", version=f"Deektator {__version__}")
    parser.add_argument("--model", type=Path, help="path to a whisper.cpp GGML model")
    parser.add_argument("--whisper", help="path to whisper-cli")
    parser.add_argument("--language", default="en", help="Whisper language code or auto (default: en)")
    parser.add_argument("--keep-fillers", action="store_true", help="retain spoken fillers in English transcripts")
    if not windows:
        parser.add_argument("--keyboard", type=Path, help="read Alt + Super from this Linux keyboard event device")
    parser.add_argument("--source", help="Windows microphone index or name" if windows else "PulseAudio microphone source name")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--manual", action="store_true", help="launch without connecting the global shortcut")
    action.add_argument("--transcribe", type=Path, metavar="AUDIO", help="print a local audio file's transcript")
    if not windows:
        action.add_argument("--install-launcher", action="store_true", help="register Deektator in your desktop launcher")
    action.add_argument("--download-model", action="store_true", help="download the higher-accuracy Whisper Small model")
    args = parser.parse_args()
    if not windows and args.install_launcher:
        print(f"Installed {install_launcher(args)}")
        return 0
    engine = Whisper(args.whisper, args.model, args.language, not args.keep_fillers)
    if args.download_model:
        try:
            print(f"Downloading {engine.small_model} (190 MB)…", file=sys.stderr)
            print(engine.download_model())
            return 0
        except (DictationError, OSError) as error:
            print(f"Deektator: {error}", file=sys.stderr)
            return 1
    if args.transcribe:
        try:
            print(engine.transcribe(args.transcribe.resolve()))
            return 0
        except (DictationError, OSError, UnicodeError) as error:
            print(f"Deektator: {error}", file=sys.stderr)
            return 1

    if windows:
        try:
            from .windows import run
        except ImportError as error:
            print(f"Deektator: run setup-windows.cmd first. {error}", file=sys.stderr)
            return 1
        return run(args, engine)

    from .desktop import Desktop, Gdk, GLib, Gtk

    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        print("Deektator: no graphical display available. Launch it from your desktop session.", file=sys.stderr)
        return 1
    try:
        install_launcher(args, replace=False)
    except (GLib.Error, OSError) as error:
        print(f"Deektator: could not create the desktop shortcut entry. {error}", file=sys.stderr)

    return Desktop(args, engine).run([sys.argv[0]])


if __name__ == "__main__":
    raise SystemExit(main())
