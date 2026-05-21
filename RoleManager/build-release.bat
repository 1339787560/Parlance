@echo off
cd /d "%~dp0"
cargo build --release
if %errorlevel% == 0 (
    copy /Y target\release\RoleManager.exe ..
    echo RoleManager.exe copied to parent directory
) else (
    echo Build failed
    exit /b %errorlevel%
)
