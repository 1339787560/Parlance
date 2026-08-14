@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---- find python: .venv > py launcher (>=3.9) > PATH python (>=3.9) > common paths ----
rem zoneinfo probe rejects <3.9 (codebase uses PEP 585 tuple[str,str]; avoids py-launcher 3.8-default trap)
set "PY="
set "PYARGS="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
)
if not defined PY (
    py -3 -c "import zoneinfo" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY=py"
        set "PYARGS=-3"
    )
)
if not defined PY (
    python -c "import zoneinfo" >nul 2>&1
    if !errorlevel! equ 0 set "PY=python"
)
if not defined PY if exist "C:\Program Files\Python313\python.exe" set "PY=C:\Program Files\Python313\python.exe"
if not defined PY if exist "C:\Program Files\Python312\python.exe" set "PY=C:\Program Files\Python312\python.exe"
if not defined PY if exist "C:\Program Files\Python311\python.exe" set "PY=C:\Program Files\Python311\python.exe"
if not defined PY set "PY=python"

"!PY!" !PYARGS! start.py %*
