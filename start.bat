@echo off
cd /d "%~dp0"
set "VENV_PYTHON=.venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" start.py %*
) else (
    python start.py %*
)
