# CPP Build & Debug Guide

> VSCode + VS2013 v120/v120_xp toolset, MSBuild/devenv.com, cppvsdbg.
> 覆盖所有 C++ 服务：游戏服（3个变体）、房间服、机器人工具、测试工程。

---

## 通用前提（所有服务共享）

| 项目 | 值 |
|------|-----|
| 环境变量 | `VS_CTLibPath=D:\LibraryVC12\`、`VS_CTNetlibPath=D:\LibraryVC12\UWL9.1;D:\LibraryVC12\tcsvr1.0;` |
| 依赖库 | `LibraryVC12_P` 下的预编译静态库（tcgament, tcgmj, xygame, uwl 等） |
| SDK/toolset | VS2013 v120（部分工程 v120_xp）通过 VS Installer 安装 |
| MFC DLL | `mfc120d.dll` 等需在 PATH 或 exe 目录 |
| 源码编码 | **全部 .cpp/.h 为 GBK** — 禁止使用 Edit/Write/Read 工具 |
| 输出编码 | 控制台输出为 GBK — `cat` 无法直接读取 |
| 构建工具 | MSBuild 或 devenv.com（均来自 VS2022 Community） |

---

## 项目一览

| 角色 | 服务 | 项目目录 | .sln | .vcxproj | ProjectName | exe | Toolset |
|------|------|----------|------|----------|-------------|-----|---------|
| CPP-GameSVR-DEV-xzmp | 金币血流血战 | `branches/douque/jinbi` | `jinbi.sln` | `gamesvr/gameSvr.vcxproj` | `xzmoSvr` | `Debug/xzmoSvr.exe` | v120 |
| CPP-GameSVR-DEV-xzmp | 银子血流血战 | `branches/douque/deposit` | `deposit.sln` | `gamesvr/gameSvr.vcxproj` | `xzmoSvr` | `Debug/xzmoSvr.exe` | v120 |
| CPP-GameSVR-DEV-xzmp | 金币六红中 | `branches/pve/zhong` | `zhong.sln` | `gamesvr/gameSvr.vcxproj` | `xzmsSvr` | `Debug/xzmsSvr.exe` | v120 |
| CPP-GameSVR-DEV-xzmp | 房间服 | `branches/pve/zhong` | — | `roomsvrxzms/roomsvrxzms.vcxproj` | `roomsvrxzms` | `Debug/roomsvrxzms.exe` | v120_xp |
| CPP-GameSVR-DEV-xzmp | 机器人工具 | `branches/pve/zhong` | — | `RobotTool/RobotTool.vcxproj` | `RobotTool` | `Debug/RobotTool.exe` | v120_xp |
| CPP-GameSVR-DEV-xzmp | 测试工程 | `branches/pve/zhong` | — | `test/test_GameSvr/test_GameSvr.vcxproj` | `test_GameSvr` | `Debug/test_GameSvr.exe` | v120 |

> 注意：xvmoSvr 有两个工作区（jinbi 和 deposit），但 ProjectName 相同均为 `xzmoSvr`。
> 房间服和机器人工具使用 `v120_xp`（支持 Windows XP 兼容），其他为 `v120`。

### 各服务 Debug 预处理器定义

| 服务 | Debug 定义 |
|------|-----------|
| xzmoSvr (jinbi/deposit) | `UWL_TRACE;WIN32;_DEBUG;_MAKECARD;_CONSOLE` |
| xzmsSvr (zhong) | `_SHOWALLCARDS;UWL_TRACE;WIN32;_DEBUG;_MAKECARD;_CONSOLE` |
| roomsvrxzms | `WIN32;_DEBUG;_CONSOLE;UWL_TRACE` 或 `UWL_SERVICE` |
| RobotTool | `WIN32;_DEBUG;_CONSOLE;UWL_TRACE;UWL_SERVICE` 或 `_RS125` 变体 |
| test_GameSvr | `WIN32;_DEBUG;_CONSOLE` |

---

## 构建方法（通用，适用于所有服务）

### 方案 A：bat 文件 + powershell（推荐）

以 xzmsSvr 为例，在项目根目录创建 `_build_debug.bat`：

```bat
@echo off
set VSCMD_SKIP_SENDTELEMETRY=1
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
msbuild gamesvr/gameSvr.vcxproj /p:Configuration=Debug /p:Platform=Win32 /p:PlatformToolset=v120 /m
```

然后执行：
```bash
powershell -Command "cmd.exe /c '_build_debug.bat'"
```

**对其他服务的适配**：只需替换 vcxproj 路径、Configuration 和 PlatformToolset。

### 方案 B：devenv.com（更简洁，无 rsp 干扰）

```bash
powershell -Command "& 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.com' 'gamesvr/gameSvr.vcxproj' '/Build' 'Debug|Win32'"
```

> **注意**：`devenv.com` 不在 PATH 中，必须使用完整路径。不要直接从 bash 调用 MSBuild.exe。

### 方案 C：VS2022 菜单打开 .sln 后 Ctrl+Shift+B

直接在 VS2022 中打开对应 `.sln`，选择 Debug|Win32 配置，构建即可。

---

## 构建前置检查

在构建前按顺序排查：

1. **确认环境变量**：`VS_CTLibPath` 和 `VS_CTNetlibPath` 已设置
2. **确认 toolset 已安装**：VS2013 v120/v120_xp 通过 VS Installer 安装
3. **杀掉残留进程**：如之前运行过 exe，先杀进程避免 LNK1104
4. **选择构建模式**：
   - **增量构建**（`/Build`）：仅修改单个 .cpp 时使用，约 0.3 秒
   - **全量重建**（`/Rebuild`）：修改 PCH、头文件包含链、或遇 LNK2011 链接错误时使用，约 2 分钟

---

## 常见陷阱

### 陷阱 1：exe 被锁定导致 LNK1104

**症状**：
```
LINK : fatal error LNK1104: 无法打开文件 xxx.exe
```

**原因**：之前运行的 exe 实例未退出，占用了文件锁。

**解决**：
```bash
# 查看进程
tasklist | grep -i xzmsSvr

# 杀掉进程（/F 在 bash 下会被解释为盘符，需包 powershell）
powershell -Command "taskkill /F /IM xzmsSvr.exe"
```

### 陷阱 2：增量链接失败 LNK2011

**症状**：
```
WinStreakModule.obj : error LNK2011: 未预先编译链接obj映像; 无法链接增量编译对象
```

**原因**：修改涉及 PCH 或头文件依赖链时，增量链接的预编译映像过期。

**解决**：改用全量重建，将 `/Build` 替换为 `/Rebuild`：
```bash
powershell -Command "& 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.com' 'gamesvr/gameSvr.vcxproj' '/Rebuild' 'Debug|Win32'"
```

### 陷阱 3：devenv.com 不在 PATH 中

**症状**：
```
devenv.com : 无法将"devenv.com"识别为 cmdlet...
```

**原因**：bash/powershell 会话未加载 VS 环境变量。

**解决**：使用完整路径 `C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.com`。

### 陷阱 4：测试模式误启动服务

**症状**：DEBUG 构建后，测试日志后紧跟着 `server initialize` 日志，服务被启动。

**原因**：`_tmain()` 中 `execAllTest()` 通过后没有 `return 0`，继续执行了 `mainServer.Initialize()`。

**正确模式**（GameSvr.cpp _tmain）：
```cpp
#ifdef DEBUG
    if (FALSE == execAllTest()) {
        UwlTrace(_T("有未通过的测试项!!!退出!!!"));
        return 0;
    }
    // 测试通过后必须 return，否则会继续启动服务
    UwlTrace(_T("所有测试通过，退出测试模式"));
    return 0;
#endif // DEBUG
```

---

## 运行服务

### 通用步骤

```bash
# 1. 先杀旧进程（如有）
powershell -Command "taskkill /F /IM xzmsSvr.exe"

# 2. 启动服务（以 xzmsSvr 为例）
powershell -Command "cmd.exe /c 'gamesvr/Debug/xzmsSvr.exe'"

# 3. 读取日志（GBK 编码，用 python 解码）
python -c "import sys; print(open(sys.argv[1],'r',encoding='gbk').read())" <output_file>
```

### 各服务 ini 文件清单

| 服务 | ini 文件 | 位置 |
|------|----------|------|
| xzmoSvr (jinbi) | `xzmoSvr.ini` | exe 目录 |
| xzmoSvr (deposit) | `xzmoSvr.ini` | exe 目录 |
| xzmsSvr (zhong) | `xzmsSvr.ini` | exe 目录 |
| roomsvrxzms | `roomsvrxzms.ini` | exe 目录 |
| RobotTool | `NodeClient.ini` | exe 目录 |

> `chCurrentDir()` 自动将工作目录切换到 exe 所在目录，所以 ini 文件放在 exe 同目录即可。

### 运行行为

- **游戏服**：调用 `execAllTest()` 运行测试 → 初始化 → 进入 `WatchInput()` 等待键盘
- **纯测试模式**（DEBUG 下 `return 0`）：执行测试 → 退出，不启动服务
- **房间服/机器人**：类似，但可能无测试逻辑
- **测试工程**：纯测试，运行后退出
- 端口占用（bind 10048）= 已有实例运行
- 键入 `q` + 回车退出

---

## 构建性能参考

| 指标 | 值 |
|------|-----|
| 增量编译（仅改 1 个 .cpp） | ~0.3 秒 |
| 全量重建 | ~2 分钟（连接大量静态库） |
| 优化 | PCH 加速编译；避免不必要的 Rebuild All |

---

## VSCode 配置模板

> `.vscode/` 目录下创建，以 xzmsSvr 为例，其他服务类似。

**launch.json** — `cppvsdbg`，`cwd` 设到对应 Debug 目录，`preLaunchTask` 触发构建。

**tasks.json** — 使用方案 A 的 bat 文件作为 task 命令。

**c_cpp_properties.json** — include 路径取自 vcxproj 的 `AdditionalIncludeDirectories`；defines 匹配 Debug 预处理器定义；`intelliSenseMode: windows-msvc-x86`。

---

## 首次接触某服务时的排查清单

1. 确认 `VS_CTLibPath` 和 `VS_CTNetlibPath` 环境变量已设置
2. 确认 v120/v120_xp toolset 已安装
3. 找到项目目录下的 `.sln` 或 `.vcxproj`
4. 从 vcxproj 中读取：ProjectName、PlatformToolset、Debug 预处理器定义、OutputFile 路径
5. 确认对应 `.ini` 文件存在于 exe 目录
6. 用方案 A 或 B 构建
7. 运行并读取 GBK 输出