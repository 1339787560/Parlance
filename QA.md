# 孤儿进程排查指南

## 什么是孤儿进程

父进程已死，子进程未退出，被 init 收养继续运行。常见于:

- Flask `debug=True` 启动 reloader → reloader 是父，Flask worker 是子
- 管理进程只杀了父（`.terminate()`），子进程脱管存活
- Windows 上 `taskkill` 没加 `/T`（不杀子树）

## 现象

| 症状 | 说明 |
|------|------|
| 端口占用 | `netstat` 显示 LISTENING，但 Task Manager 找不到对应进程 |
| 服务正常 | 端口还可访问（孤儿仍在工作） |
| 重启失败 | 新实例启动时报 `Address already in use` |
| PID 幽灵 | `netstat` 显示 PID，`taskkill` / `tasklist` / `Stop-Process` 都说找不到 |

## 排查步骤

### 1. 找端口占用者

```batch
netstat -ano | findstr :5001
```

输出示例:
```
TCP    0.0.0.0:5001    0.0.0.0:0    LISTENING    11100
TCP    192.168.10.28:5001    192.168.10.28:34195    ESTABLISHED    11100
```

记下 PID（此处 11100）。

### 2. 验证进程是否存在

```batch
tasklist /FI "PID eq 11100" /V
```

或 PowerShell:
```powershell
Get-Process -Id 11100 -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "ProcessId = 11100"
```

**全空 = 进程已死，TCP 表残留父 PID 引用。** 孤儿进程通常有不同 PID。

### 3. 按工作目录/命令行找真实进程

已知服务启动路径时最有效:

```powershell
Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { $_.CommandLine -like "*HttpPhotoServer*" }
```

输出:
```
ProcessId   : 41548
Name        : python.exe
CommandLine : D:\Compiler\python\python.exe C:\codelib\HttpPhotoServer\src\main.py
SessionId   : 1
```

此例: netstat 显示 PID 11100（已死 reloader），但真实 worker 在 41548。

也可搜工作目录（需 Sysinternals handle.exe）或遍历可疑进程按路径筛选。

### 4. 查看 TCP 连接详情

```powershell
Get-NetTCPConnection -LocalPort 5001 | Select-Object LocalAddress, LocalPort, State, OwningProcess, CreationTime
```

```powershell
Get-NetTCPConnection -LocalPort 5001 | Select-Object *
```

`ProcessPath` / `ProcessName` / `SessionId` 为空 = 进程对管理 API 不可见，孤儿确认。

## 清理方法

### 按真实 PID 杀

```powershell
Stop-Process -Id 41548 -Force
```

### 按命令行特征批量杀

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*HttpPhotoServer*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### Windows 注意: MSYS2 路径转义

Git Bash 会把 `/F` 转成 `F:/`，需用 `//F` 或 cmd 绕过:

```batch
cmd.exe /c "taskkill /F /T /PID 11100"
```

```powershell
# PowerShell 无此问题
taskkill /F /T /PID 11100
```

### 端口释放确认

```powershell
Get-NetTCPConnection -LocalPort 5001 -ErrorAction SilentlyContinue
# 无输出 = 已释放
```

### 最后手段

重启机器。TCP 表残留无法软件释放时唯一解。

## 预防

| 措施 | 说明 |
|------|------|
| 杀进程树 | Windows: `taskkill /F /T /PID`，Unix: `kill -SIGKILL -pgid` |
| 关 debug 模式 | Flask `debug=True` → reloader 双进程，改为 `debug=False` |
| 记录子 PID | 跟踪进程树，stop 时逐级清理 |
| 端口检测启动 | 启动前检查端口占用，先清理再启动 |
