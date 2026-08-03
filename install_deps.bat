@echo off
setlocal enabledelayedexpansion
rem infoServer chain dependency installer
rem installs root + serviceGroup/serviceServer-legacy requirements.txt
rem usage: install_deps.bat [--python "path\to\python.exe"]
cd /d "%~dp0"

rem ---- find python: --python arg > .venv > py launcher > common paths > python ----
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

echo ============================================
echo   infoServer chain dependency install
echo   Python: !PY! !PYARGS!
echo ============================================

set "REQ1=requirements.txt"
set "REQ2=serviceGroup\serviceServer-legacy\requirements.txt"

for %%R in ("!REQ1!" "!REQ2!") do (
    if exist %%R (
        echo.
        echo   [install] %%R
        "!PY!" !PYARGS! -m pip install -r "%%~R"
        if !errorlevel! geq 1 goto :fail
    ) else (
        echo   [skip] not found: %%R
    )
)

echo.
echo ============================================
echo   verify core modules
echo ============================================
"!PY!" !PYARGS! -c "import flask, requests, yaml, uvicorn, fastapi, mysql.connector, oss2, cryptography; print('core deps OK')"
if !errorlevel! geq 1 goto :fail

echo.
echo   all dependencies installed.
pause
exit /b 0

:fail
echo.
echo   INSTALL FAILED.
pause
exit /b 1
