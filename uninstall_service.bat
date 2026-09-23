@echo off
setlocal enabledelayedexpansion
rem ============================================================================
rem  uninstall_service.bat - remove infoServer boot auto-start
rem
rem  Mechanism: Windows Task Scheduler job named "InfoServer"
rem             (registered by startup.py install; see startup.py TASK_NAME)
rem
rem  usage:
rem    uninstall_service.bat            remove auto-start (idempotent)
rem    uninstall_service.bat status     only show current status
rem    uninstall_service.bat stop       remove auto-start AND quit the running stack
rem
rem  Auto-elevates via UAC (deleting a boot task requires admin).
rem  Safe to run when nothing is installed -> reports "not present" and exits 0.
rem
rem  NOTE: keep this file ASCII-only + CRLF. cmd.exe under cp936 mangles UTF-8
rem        Chinese and can swallow the following line (see repo pitfall log).
rem ============================================================================

cd /d "%~dp0"

set "TASK_NAME=InfoServer"
set "ACTION=%~1"

if /i "%ACTION%"=="help" goto :help
if /i "%ACTION%"=="-h"   goto :help
if /i "%ACTION%"=="/?"   goto :help

rem ---- status is read-only: handle it BEFORE elevating (no UAC prompt) ----
if /i "%ACTION%"=="status" goto :status

rem ---- elevate: schtasks /Delete of a boot task requires admin ----
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin privileges...
    rem NOTE: never pass -ArgumentList when empty. PowerShell rejects an empty value
    rem       with "Cannot validate argument on parameter 'ArgumentList'" (Chinese
    rem       Windows localizes it as the parameter-validation error), and the
    rem       elevation silently fails, so a plain double-click would do nothing.
    rem       Hence the branch below.
    if defined ACTION (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%ACTION%' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    )
    exit /b
)

echo.
echo ============================================================
echo   Removing infoServer auto-start  (task: %TASK_NAME%)
echo ============================================================
echo.

rem ---- step 1: prefer the repo's own uninstaller (single source of truth) ----
set "DID=0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    py -3 --version >nul 2>&1
    if !errorlevel! equ 0 set "PY=py"
)

if defined PY (
    if exist "startup.py" (
        echo [1/2] running: startup.py uninstall
        "%PY%" startup.py uninstall
        if !errorlevel! equ 0 set "DID=1"
        if !DID! equ 0 echo   [warn] startup.py uninstall failed - falling back to schtasks.
    )
)

rem ---- step 2: fallback / belt-and-braces: delete the task directly ----
if !DID! equ 0 (
    echo [1/2] direct: schtasks /Delete /TN %TASK_NAME% /F
    schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1
    if !errorlevel! neq 0 (
        echo   [info] task not present - nothing to delete.
    ) else (
        echo   [OK] task deleted.
    )
)

echo.
echo [2/2] verify
schtasks /Query /TN "%TASK_NAME%" >nul 2>&1
if !errorlevel! equ 0 (
    echo   [FAIL] task "%TASK_NAME%" still exists.
    echo          Make sure this script ran as Administrator.
    set "RC=1"
) else (
    echo   [OK] no "%TASK_NAME%" task found - auto-start is removed.
    set "RC=0"
)

if /i "%ACTION%"=="stop" (
    echo.
    echo [extra] quitting the running stack via the host control pipe...
    if exist "ctl_client.py" (
        if defined PY (
            "%PY%" ctl_client.py --socket ctl quit
        ) else (
            echo   [warn] no python found - cannot call ctl_client.py
        )
    ) else (
        echo   [warn] ctl_client.py not found - skip.
    )
    echo   NOTE: do NOT taskkill the host directly - the monitor will restart it.
)

echo.
if "!RC!"=="0" (
    echo DONE. Auto-start removed.
) else (
    echo DONE WITH ERRORS. See messages above.
)
pause
exit /b !RC!

:status
echo.
echo ============================================================
echo   infoServer auto-start status  (task: %TASK_NAME%)
echo ============================================================
schtasks /Query /TN "%TASK_NAME%" /FO LIST /V >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] task EXISTS - auto-start is ENABLED
    echo.
    schtasks /Query /TN "%TASK_NAME%" /FO LIST /V
) else (
    echo   [--] task NOT found - auto-start is DISABLED
    echo        ^(if you believe it IS installed, re-run this as Administrator -^)
)
echo.
rem also show whether the stack is currently running
echo   running stack (start.py --supervise):
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like '%%python%%'\" | Where-Object { $_.CommandLine -match 'start\.py' } | ForEach-Object { '     pid=' + $_.ProcessId + '  ' + $_.CommandLine }"
pause
exit /b 0

:help
echo.
echo   usage: uninstall_service.bat [status^|stop^|help]
echo.
echo     (no arg)  remove the boot auto-start task "%TASK_NAME%"
echo     status    only show whether auto-start is registered
echo     stop      remove auto-start, then quit the running stack
echo     help      this text
echo.
echo   Equivalent built-in path:  install_service.bat uninstall
echo.
pause
exit /b 0
