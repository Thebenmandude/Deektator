import os
from pathlib import Path

source = Path(os.environ["DEEKTATOR_PACKAGE_SOURCE"])
analysis = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(source)],
    datas=[(str(source / "whisper"), "whisper")],
    excludes=["gi"],
)
modules = PYZ(analysis.pure)
desktop = EXE(modules, analysis.scripts, [], exclude_binaries=True, name="Deektator", console=False, upx=False)
command = EXE(modules, analysis.scripts, [], exclude_binaries=True, name="deektator-cli", console=True, upx=False)
bundle = COLLECT(desktop, command, analysis.binaries, analysis.datas, name="Deektator", upx=False)
