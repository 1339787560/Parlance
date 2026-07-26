@echo off
cd /d "D:\Codlib\VscodeCodlib\Python\infoServer"
set "VENV_PYTHON=.venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" start.py %*
) else (
    "D:\Compiler\python\python.exe" start.py %*
)
