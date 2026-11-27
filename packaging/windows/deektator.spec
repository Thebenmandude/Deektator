import os
from pathlib import Path

source = Path(os.environ["DEEKTATOR_PACKAGE_SOURCE"])
analysis = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(source)],
    datas=[(str(source / "whisper"), "whisper")],
    excludes=["gi"],
)
# The portable bundle uses the standard x64 PortAudio library.
analysis.binaries = [
    entry
    for entry in analysis.binaries
    if not Path(entry[0]).name.startswith("libportaudio") or Path(entry[0]).name == "libportaudio64bit.dll"
]
modules = PYZ(analysis.pure)
desktop = EXE(modules, analysis.scripts, [], exclude_binaries=True, name="Deektator", console=False, upx=False)
command = EXE(modules, analysis.scripts, [], exclude_binaries=True, name="deektator-cli", console=True, upx=False)
bundle = COLLECT(desktop, command, analysis.binaries, analysis.datas, name="Deektator", upx=False)
