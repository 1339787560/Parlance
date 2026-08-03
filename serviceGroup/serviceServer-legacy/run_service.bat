@echo off
setlocal enabledelayedexpansion

:: Check for administrator privileges
NET SESSION >nul 2>&1
if %errorLevel% neq 0 (
    echo "Requesting administrator privileges..."
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /B
)

:: Change to script directory
cd /d %~dp0

:: Ensure required cache directories exist
if not exist "src\cache\icons" mkdir "src\cache\icons"
if not exist "src\cache\backgrounds" mkdir "src\cache\backgrounds"
if not exist "src\cache\benchmarks" mkdir "src\cache\benchmarks"
if not exist "src\background" mkdir "src\background"

:: Check if Python is installed
where python >nul 2>&1
if %errorLevel% neq 0 (
    echo "Error: Python not found. Please install Python and add it to system path."
    pause
    exit /B
)
:: Upgrade pip to latest version
echo "Upgrading pip..."
python -m pip install --upgrade pip

:: Install/Upgrade all necessary dependencies
echo "Installing/Upgrading all dependencies from requirements.txt..."
python -m pip install -r requirements.txt

:: Upgrade requests and its dependencies to fix compatibility warnings
echo "Fixing requests dependency compatibility..."
python -m pip install --upgrade requests urllib3 charset-normalizer

:: Install Playwright browser binaries
echo "Installing Playwright Chromium..."
python -m playwright install chromium

:: Run main.py script
echo "Starting service with administrator privileges..."
python main.py

:: Prevent window from closing automatically
pause
