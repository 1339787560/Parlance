@echo off
cd /d "%~dp0"

rem ---- find python: .venv > py launcher > common paths > python ----
set "PY="
set "PYARGS="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    py -3 --version >nul 2>&1 && set "PY=py" && set "PYARGS=-3"
)
if not defined PY if exist "C:\Program Files\Python313\python.exe" set "PY=C:\Program Files\Python313\python.exe"
if not defined PY if exist "C:\Program Files\Python312\python.exe" set "PY=C:\Program Files\Python312\python.exe"
if not defined PY if exist "C:\Program Files\Python311\python.exe" set "PY=C:\Program Files\Python311\python.exe"
if not defined PY set "PY=python"

"%PY%" %PYARGS% start.py %*
