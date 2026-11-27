@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Run setup-windows.cmd first.
    exit /b 1
)
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
"%~dp0.venv\Scripts\python.exe" -P -m deektator %*
exit /b %errorlevel%
