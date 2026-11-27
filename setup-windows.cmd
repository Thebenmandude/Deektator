@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv || exit /b 1
)
".venv\Scripts\python.exe" -m pip install "sounddevice==0.5.6" || exit /b 1
".venv\Scripts\python.exe" -m deektator.setup_windows
exit /b %errorlevel%
