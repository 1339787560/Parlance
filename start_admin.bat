@echo off
setlocal enabledelayedexpansion
rem infoServer Admin Launcher
rem Double-click to run with UAC elevation

fsutil dirty query %SystemDrive% >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   infoServer (Admin)
echo   CWD: %cd%
echo ============================================
echo.

rem ---- find python: .venv > py launcher > common paths > python ----
set "PY="
set "PYARGS="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    py -3 --version >nul 2>&1
    if !errorlevel! equ 0 (
        set "PY=py"
        set "PYARGS=-3"
    )
)
if not defined PY if exist "C:\Program Files\Python313\python.exe" set "PY=C:\Program Files\Python313\python.exe"
if not defined PY if exist "C:\Program Files\Python312\python.exe" set "PY=C:\Program Files\Python312\python.exe"
if not defined PY if exist "C:\Program Files\Python311\python.exe" set "PY=C:\Program Files\Python311\python.exe"
if not defined PY set "PY=python"

"!PY!" !PYARGS! start.py %*

echo.
pause
