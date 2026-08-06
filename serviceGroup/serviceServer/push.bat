@echo off
:: service-server 编译 + 落位 + svn 分发 (闭环 dev 编译 → svn 分发)
:: 用法: push.bat [commit message]   缺省消息 = "serviceServer: build"
:: 作用域: serviceGroup/serviceServer + serviceGroup/serviceServer-legacy 两目录
::   (对齐 SDD serviceServer-子服务自动更新: svn 范围仅此两目录)
:: 前置: svn CLI + infoServer 目录已 svn checkout (凭据缓存, 非交互)
::   push 后 bastion 侧用 ctl_client --socket svc update 拉取 (infoServer 提供断点)
cd /d "%~dp0"

set MSG=%~1
if "%MSG%"=="" set MSG=serviceServer: build

:: 1) 编译 + 落位根 exe (config.yaml command 指向根 exe)
echo === build + 落位根 exe ===
call build.bat
if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

:: 2) 切到 svn 工作副本根 (infoServer 根, .svn 在根)
cd /d "%~dp0..\.."

:: 3) svn add 新增文件 (仅 ? 状态, 跳过 target/ 构建产物)
echo === svn add (unversioned, skip target/) ===
for /f "tokens=1,* delims= " %%a in ('svn status serviceGroup\serviceServer serviceGroup\serviceServer-legacy 2^>nul') do (
    if "%%a"=="?" (
        echo "%%b" | findstr /i "\\target\\" >nul 2>&1 || svn add "%%b" >nul 2>&1
    )
)

:: 4) svn commit 分发 (仅两目录, 不碰其余子服务/launcher)
echo === svn commit: %MSG% ===
svn commit -m "%MSG%" serviceGroup\serviceServer serviceGroup\serviceServer-legacy
if errorlevel 1 (
    echo COMMIT FAILED
    exit /b 1
)
echo === done: serviceServer pushed to svn ===
echo  bastion 侧更新: ssh 后 ctl_client.py --socket svc update
