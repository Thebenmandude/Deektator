"""Install the Windows CPU runtime and default offline model."""

import hashlib
import platform
import shutil
import struct
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .engine import WINDOWS_WHISPER, DictationError, Whisper


RUNTIME_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.3/whisper-bin-x64.zip"
RUNTIME_SHA256 = "d824b1e37599f882b396e73f1ee0bfd5d0529f700314c48311dcbd00b803321d"


def install_runtime(destination=WINDOWS_WHISPER):
    executable = destination / "whisper-cli.exe"
    if executable.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runtime-", dir=destination.parent) as folder:
        archive = Path(folder) / "whisper.zip"
        print("Downloading the whisper.cpp CPU runtime…", flush=True)
        with urllib.request.urlopen(RUNTIME_URL, timeout=30) as response, archive.open("wb") as target:
            shutil.copyfileobj(response, target)
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != RUNTIME_SHA256:
                raise DictationError("The Whisper runtime did not match its published checksum.")
        staging = Path(folder) / "runtime"
        staging.mkdir()
        with zipfile.ZipFile(archive) as package:
            for member in package.namelist():
                name = PurePosixPath(member).name
                if name == executable.name or name == "whisper.dll" or (name.startswith("ggml") and name.endswith(".dll")):
                    with package.open(member) as source, (staging / name).open("wb") as target:
                        shutil.copyfileobj(source, target)
        if not (staging / executable.name).is_file():
            raise DictationError("The Whisper archive does not contain whisper-cli.exe.")
        try:
            staging.rename(destination)
        except FileExistsError:
            if not executable.is_file():
                raise


def main():
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64") or struct.calcsize("P") != 8:
        print("Deektator setup requires 64-bit x86 Windows and 64-bit Python.", file=sys.stderr)
        return 1
    try:
        install_runtime()
        engine = Whisper(str(WINDOWS_WHISPER / "whisper-cli.exe"), None, "en", True)
        if not engine.model.is_file():
            print("Downloading the default Whisper model (190 MB)…", flush=True)
            engine.download_model()
        engine.validate()
    except (DictationError, OSError, zipfile.BadZipFile) as error:
        print(f"Deektator setup: {error}", file=sys.stderr)
        return 1
    print("Setup complete. Start Deektator with run-deektator.cmd.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
