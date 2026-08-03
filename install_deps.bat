@echo off
rem infoServer chain dependency installer
rem installs root + serviceGroup/serviceServer-legacy requirements.txt
rem usage: install_deps.bat [python-path]
cd /d "%~dp0"

set "PY=python"
if not "%~1"=="" set "PY=%~1"

echo ============================================
echo   infoServer chain dependency install
echo   Python: %PY%
echo ============================================

set "REQ1=requirements.txt"
set "REQ2=serviceGroup\serviceServer-legacy\requirements.txt"

for %%R in ("%REQ1%" "%REQ2%") do (
    if exist %%R (
        echo.
        echo   [install] %%R
        %PY% -m pip install -r "%%~R"
        if errorlevel 1 goto :fail
    ) else (
        echo   [skip] not found: %%R
    )
)

echo.
echo ============================================
echo   verify core modules
echo ============================================
%PY% -c "import flask, requests, yaml, uvicorn, fastapi, mysql.connector, oss2, cryptography; print('core deps OK')"
if errorlevel 1 goto :fail

echo.
echo   all dependencies installed.
pause
exit /b 0

:fail
echo.
echo   INSTALL FAILED.
pause
exit /b 1
