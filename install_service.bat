@echo off
rem ============================================
rem   infoServer auto-start installer
rem   usage:
rem     install_service.bat install    (register auto-start)
rem     install_service.bat uninstall  (remove auto-start)
rem     install_service.bat status     (check status)
rem     install_service.bat            (no arg = help)
rem   install/uninstall auto-elevate via UAC
rem ============================================

cd /d "%~dp0"

set "ACTION=%~1"
if "%ACTION%"=="" goto :help

rem ---- find python: --python arg > .venv > py launcher > common paths > python ----
rem py launcher (C:\Windows\py.exe) immune to PATH pollution (e.g. "Program Files" space)
rem usage: install_service.bat install --python "C:\Program Files\Python313\python.exe"
set "PY="
set "PYARGS="
set "NEXT="
for %%a in (%*) do (
    if defined NEXT (
        set "PY=%%~a"
        set "NEXT="
    ) else if /i "%%~a"=="--python" (
        set "NEXT=1"
    )
)

if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    py -3 --version >nul 2>&1 && set "PY=py" && set "PYARGS=-3"
)
if not defined PY if exist "C:\Program Files\Python313\python.exe" set "PY=C:\Program Files\Python313\python.exe"
if not defined PY if exist "C:\Program Files\Python312\python.exe" set "PY=C:\Program Files\Python312\python.exe"
if not defined PY if exist "C:\Program Files\Python311\python.exe" set "PY=C:\Program Files\Python311\python.exe"
if not defined PY set "PY=python"

if /i "%ACTION%"=="install" goto :need_admin
if /i "%ACTION%"=="uninstall" goto :need_admin
if /i "%ACTION%"=="status" goto :status
goto :help

:need_admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges...
    powershell -Command "Start-Process '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
)

if /i "%ACTION%"=="install" goto :install
if /i "%ACTION%"=="uninstall" goto :uninstall

:install
echo.
echo ============================================
echo   Installing infoServer auto-start...
echo ============================================
"%PY%" %PYARGS% startup.py install
if errorlevel 1 (
    echo.
    echo   [FAIL] install failed.
    pause
    exit /b 1
)
echo.
echo   [OK] auto-start installed. All sub-services will start on boot.
pause
exit /b 0

:uninstall
echo.
echo ============================================
echo   Removing infoServer auto-start...
echo ============================================
"%PY%" %PYARGS% startup.py uninstall
if errorlevel 1 (
    echo.
    echo   [FAIL] uninstall failed.
    pause
    exit /b 1
)
echo.
echo   [OK] auto-start removed.
pause
exit /b 0

:status
echo.
echo ============================================
echo   infoServer auto-start status...
echo ============================================
"%PY%" %PYARGS% startup.py status
pause
exit /b 0

:help
echo.
echo   usage: install_service.bat [install^|uninstall^|status]
echo.
echo     install    register auto-start (Windows Task Scheduler)
echo     uninstall  remove auto-start
echo     status     show current auto-start status
echo.
pause
exit /b 0
