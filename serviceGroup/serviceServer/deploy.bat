@echo off
rem service-server publish (since 2026-09-21: single pack + static resources, replaces svn distribution)
rem
rem usage: deploy.bat [target] [extra args...]
rem   target default 127.0.0.1:5099 (local legacy deploy gateway); also 192.168.102.53:5099
rem   e.g.  deploy.bat                                -> local
rem         deploy.bat 192.168.102.53:5099            -> bastion 53
rem         deploy.bat 192.168.102.53:5099 --token X   -> remote with deploy token
rem
rem scope: serviceServer-rust (its assets incl. serviceServer-legacy dir) = ONE pack
rem   -> make_deploy_pack.py --only serviceServer-rust --push <target>:5099
rem   -> remote legacy: unzip+verify -> non-exe replaced in place (backup) -> exe handed
rem      to host swap_exe (stop/replace/start) -> rollback on any failure
rem   -> progress: GET /api/deploy/log on the target (record: exe_done / failures / host_probe)
rem
rem why NOT build.bat: build.bat copies the exe onto the running path, but a live
rem   service-server.exe is locked by the Windows image section (copy always fails). The pack
rem   carries target/release via exe_src, and the target host performs the swap.
rem
rem why :5099 and not :5000: while swapping, :5000 itself is the target being stopped.
rem why .venv python: system python has no PyYAML, so packing fails (measured 2026-09-21).
cd /d "%~dp0"

set TARGET=%~1
if "%TARGET%"=="" set TARGET=127.0.0.1:5099
echo %TARGET% | findstr /i "^http" >nul || set TARGET=http://%TARGET%

set PY=%~dp0..\..\.venv\Scripts\python.exe
if not exist "%PY%" (
    echo [ERROR] venv python not found: %PY%
    exit /b 1
)

echo === 1/3 build: cargo build --release (no copy onto running path) ===
cargo build --release
if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo === 2/3 pack (serviceServer-rust + serviceServer-legacy) + push %TARGET% ===
cd /d "%~dp0..\.."
"%PY%" make_deploy_pack.py --only serviceServer-rust --push %TARGET% %2 %3 %4 %5 %6 %7 %8 %9
if errorlevel 1 (
    echo DEPLOY FAILED - check /api/deploy/log on the target
    exit /b 1
)

echo === 3/3 done: service-server published as one pack (rust exe swapped by host; legacy py/templates replaced + self-restart) ===
