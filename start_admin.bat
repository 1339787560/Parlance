@echo off
:: infoServer Admin Launcher
:: Double-click to run with UAC elevation

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

set "VENV_PYTHON=.venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" start.py %*
) else (
    python start.py %*
)

echo.
pause
