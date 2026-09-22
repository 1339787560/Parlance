@echo off
REM ============================================================================
REM build_assetTool.bat - freeze assetTool.py into a single-file assetTool.exe
REM
REM Why: the asset-fetch helper is the only playwright consumer that ships in a
REM deploy pack, and playwright drags a Node driver + a browser cache. Freezing
REM makes it ONE callable binary with no Python env / no site-packages needed on
REM the target machine. The browser comes from the SYSTEM (channel=chrome/msedge
REM in assetTool.py), so the ~1.7GB ms-playwright cache is not required either.
REM
REM Prereqs (same interpreter): playwright + pyinstaller
REM   python -m pip install playwright pyinstaller
REM
REM Usage:  build_assetTool.bat [path\to\python.exe]
REM Output: assetTool.exe next to this script (a BUILD ARTIFACT - not committed;
REM         make_deploy_pack.py picks it up from disk like target/release/*.exe)
REM
REM NOTE: keep this file ASCII-only + CRLF. cmd.exe under cp936 mangles UTF-8
REM       Chinese and can split lines (see SDD pitfall log).
REM ============================================================================
setlocal

set "HERE=%~dp0"
set "PY=%~1"
if "%PY%"=="" set "PY=python"

echo [build_assetTool] python = %PY%
echo [build_assetTool] output = %HERE%assetTool.exe

"%PY%" -m PyInstaller --onefile --noconfirm --clean ^
  --name assetTool ^
  --collect-all playwright ^
  --distpath "%HERE%." ^
  --workpath "%TEMP%\assetTool_build" ^
  --specpath "%TEMP%\assetTool_build" ^
  "%HERE%assetTool.py"

if errorlevel 1 (
  echo [build_assetTool] BUILD FAILED
  exit /b 1
)

echo [build_assetTool] done.
endlocal
