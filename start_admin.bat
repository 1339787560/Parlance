@echo off
:: infoServer Admin Launcher
:: Double-click to run with UAC elevation

fsutil dirty query %SystemDrive% >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "D:\Codlib\VscodeCodlib\Python\infoServer"

echo ============================================
echo   infoServer (Admin)
echo   CWD: %cd%
echo ============================================
echo.

"D:\Compiler\python\python.exe" main.py

echo.
pause
