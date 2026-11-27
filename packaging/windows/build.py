"""Build a portable Windows release using the project runtime installer."""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from importlib.metadata import distribution
from pathlib import Path

from deektator.setup_windows import install_runtime


def copy_notices(destination):
    destination.mkdir()
    notices = {
        "Python.txt": f"https://raw.githubusercontent.com/python/cpython/v{platform.python_version()}/LICENSE",
        "whisper.cpp.txt": "https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.8.3/LICENSE",
        "Tcl.txt": "https://raw.githubusercontent.com/tcltk/tcl/core-8-6-14/license.terms",
        "Tk.txt": "https://raw.githubusercontent.com/tcltk/tk/core-8-6-14/license.terms",
    }
    for filename, url in notices.items():
        with urllib.request.urlopen(url, timeout=30) as response, (destination / filename).open("wb") as output:
            shutil.copyfileobj(response, output)

    for name in ("sounddevice", "cffi", "pycparser", "pyinstaller"):
        package = distribution(name)
        for file in package.files or []:
            if file.name.lower().startswith(("license", "copying")) and file.locate().is_file():
                target = destination / name / file.name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(file.locate(), target)


def main(version, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="deektator-package-") as directory:
        work = Path(directory)
        source = work / "source"
        shutil.copytree(root / "deektator", source / "deektator", ignore=shutil.ignore_patterns("__pycache__"))
        (source / "deektator" / "_release_version.py").write_text(f"VERSION = {version!r}\n", encoding="utf-8")
        install_runtime(source / "whisper")
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--distpath", str(work / "dist"), "--workpath", str(work / "build"),
                str(root / "packaging/windows/deektator.spec"),
            ],
            cwd=work,
            env={**os.environ, "PYTHONPATH": str(source), "DEEKTATOR_PACKAGE_SOURCE": str(source)},
            check=True,
        )
        bundle = work / "dist" / "Deektator"
        shutil.copyfile(root / "README.md", bundle / "README.md")
        copy_notices(bundle / "Third-party licenses")
        shutil.make_archive(str(output / f"Deektator-{version}-windows-x64"), "zip", bundle.parent, bundle.name)


if __name__ == "__main__":
    main(*sys.argv[1:])
