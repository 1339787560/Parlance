@echo off
:: service-server 编译 + 落位到本目录根
:: config.yaml serviceServer-rust command 指向根 exe, 无需手动 cp 版本目录
cd /d "%~dp0"

echo === cargo build --release ===
cargo build --release
if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo === copy to serviceServer\service-server.exe ===
copy /Y target\release\service-server.exe service-server.exe
if errorlevel 1 (
    echo COPY FAILED
    exit /b 1
)

echo === done: service-server.exe ready in %~dp0 ===
