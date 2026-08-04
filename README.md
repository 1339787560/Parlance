# infoServer · 可插拔服务组托管框架

> **纯进程启动器（host，无 HTTP、不占端口）+ ServiceGroupManager（Job Object 托管）+ 一组自包含子服务。**
> 所有子服务由 `config.yaml` 声明，`enabled` 即装/卸 → 可拆卸。

原 Service-Svr-Dev 于 2026-07-16 并入。技术栈：Python 3（FastAPI / Flask）+ Rust 1.x（service-server）。

---

## 架构

```
infoServer host (main.py — 纯启动器, 无 HTTP, 不占端口)
  └─ ServiceGroupManager (service_manager.py — Job Object 托管, 父退出→子终止)
     ├─ parlance-chat    :5001  serviceGroup/parlanceChat        局域网聊天/文件共享 (FastAPI+SSE)
     ├─ serviceServer    :5000  serviceGroup/serviceServer        Rust 工具服务 (前台)
     │     └─ strangler 反代 → :5099  serviceServer-legacy       旧 Flask (渐进瘦身至退役)
     ├─ statistic        :5002  serviceGroup/statisticServer     DeepSeek 代理统计
     ├─ debug-relay      :5003  serviceGroup/debugRelay          真机调试中继
     ├─ np-reader        :8000  ../Novel-Pineline                小说阅读器
     ├─ hair-sim         :8765  ../hair-sim                      发型模拟器 (macOS)
     └─ cocos-creator    :3000  外部                             Cocos 编辑器 (默认 disabled)
```

- **纯壳原则**：host 对子服务零硬 import / 零初始化依赖。
- **可拆卸**：只想用某子服务 → `config.yaml` 关其余 `enabled=false`，或跳过 host 直跑子服务入口（如 `python serviceGroup/debugRelay/debug_relay.py`）。
- **host 不再有 HTTP**：原 `/api/services/*` `/api/cocos-mcp/*` 管理 SPA 已删（2026-07-16）；管理 = 改 `config.yaml` + 重启。

---

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动

```bash
python start.py            # 跨平台入口 (win/mac 共用), 默认键盘模式
python start.py --no-input # 服务模式 (无键盘监听)
```

**入口链**：`start.bat` / `start.command` → `start.py` → `run.py` → `main.py`。

`start.py` 解析项目 `.venv` 解释器后启动 `run.py`，argv 透传；Windows 用 `subprocess`（规避 `os.execvp` 对含空格路径的拆词 bug），POSIX 用 `execvp`（Ctrl+C 信号直达）。

### 局域网聊天访问

同局域网设备打开 `http://<服务端IP>:5001` 即可收发消息/传文件，无需账号/客户端。

---

## 配置 (`config.yaml`)

单一开关板。**改完必调 `cwd_infoserver_reload()` 或键盘 `r` 重启 host 生效**（host 不热读 config）。

```yaml
server:
  host: 0.0.0.0
  port: 5001    # run.py 预清理此端口 (为 parlanceChat 让出); host 自身不绑定

services:
  - name: serviceServer-rust
    command: ./serviceGroup/serviceServer/service-server.exe
    cwd: ./serviceGroup/serviceServer
    port: 5000
    auto_restart: true
    enabled: true
    env:
      SERVICESVR_CONFIG: ../serviceServer-legacy/config.json
      SERVICESVR_LEGACY_URL: http://127.0.0.1:5099
      RUST_LOG: info
```

**字段**：`managed`(默认 true, Job Object 绑定) / `port`(启动前预清理占用进程) / `auto_restart`(崩溃重启) / `enabled`(开关) / `tags`(分组) / `managed=false`(守护，父退出存活)。

---

## 控制面（无需 cd infoServer）

### 1. stdio MCP（agent 首选，跨角色通用）

注册在 `.mcp.json:cwd-mcp`，每角色会话自动加载：

| 工具 | 等价 CLI | 用途 |
|---|---|---|
| `cwd_infoserver_reload` | `ctl_client reload` | stop+start launcher，子服务全重启（~15-30s） |
| `cwd_infoserver_status` | `ctl_client status` | launcher 状态 + 托管服务清单 |
| `cwd_infoserver_services` | `--socket svc services` | 查询托管服务清单（config 权威） |
| `cwd_infoserver_restart(port)` | `--socket svc restart` | **按端口重启单个子服务**（不影响其他） |
| `cwd_infoserver_swap_exe(port)` | `--socket svc swap_exe` | **热替换 .exe 二进制**（stop+sleep2+cp target/release+start，规避文件占用） |
| `cwd_infoserver_start/stop/quit` | `start/stop/quit` | 启 / 停 / 退出 |

> **托管检查约定**：重启/重载任何服务前，先 `cwd_infoserver_services()` 确认是否由 infoserver 托管；同会话已查则复用。

### 2. CLI (`ctl_client.py`)

```bash
python ctl_client.py reload                                              # launcher 重载
python ctl_client.py status                                              # launcher 状态
python ctl_client.py --socket svc services                               # 服务组清单
python ctl_client.py --socket svc restart --params '{"port": 5000}'      # 重启单服务
python ctl_client.py --socket svc swap_exe --params '{"port": 5000}'     # 热换 exe
python ctl_client.py --socket svc update                                 # svn 更新编排 (停→svn up→启)
```

`--socket`：`ctl`=launcher (run.py, 默认) / `svc`=服务组 (main.py)。底层 = JSON-RPC 2.0 over `multiprocessing.connection`（Win Named Pipe `\\.\pipe\infoserver_{ctl,svc}` / POSIX UDS）。

---

## serviceServer (:5000) — Rust 工具服务

Rust 重写（`serviceGroup/serviceServer/`），前台 :5000 自处理路由，未匹配请求 strangler 反代到旧 Flask :5099。构建/测试/架构详见 [serviceGroup/serviceServer/AGENTS.md](serviceGroup/serviceServer/AGENTS.md)。

### 文件访问簇（堡垒机文件读写）

**沙箱** = 服务根 `abspath/name/type`（`src/path_check.rs` 分量比较，修旧 `startswith` prefix bug，越界 403）。源 = `config.json` 的 `abspath` + `service` 段。

| 接口 | 行为 | 扩展名限制 |
|---|---|---|
| `GET /api/config/files?serviceId=` | 列服务根下**所有文件** | 不限（含 exe/dll/dmp/log/pdb） |
| `GET /api/config/file/content?filePath=` | 读**任意文件**（编码自动探测 utf-8/gbk/utf-16/latin-1 兜底） | 不限 |
| `GET /api/config/file/download?filePath=` | **下载任意文件**（二进制兜底，上限 200MB，RFC 5987 中文文件名） | 不限 |
| `POST /api/config/file/save` | **改配置**（滚动备份 `.config_history/<filename>/` max3 + 原子写 tmp+rename） | **仅 ini/json/lua** |
| `GET\|POST\|DELETE /api/config/file/{branches,create_branch,switch_branch,remove_branch}` | 分支配置管理（切换前备份原文件到 `remove/`） | 同 save |

> **写保护**：save 流程 = 路径校验 → 扩展名白名单 → 编码 strict（失败原文件未动）→ 滚动备份原文件 → 原子写（tmp+rename，失败零变更）。单次误清空可从 `.config_history/` 恢复。
>
> **旧 `/api/fileontimer/*`（CWD 沙箱 flask 文件遍历）已废弃**：`src/proxy.rs` `DEAD_PREFIXES` 黑名单，前台直接 404 不反代 legacy。

### 服务控制簇

| 接口 | 用途 |
|---|---|
| `GET /api/services/status` | 全服务状态（Win32 SCM + ports 探测，TTL 缓存 10s） |
| `GET /api/config/services/running` | 运行中服务（`configHide` 过滤，配置编辑页用） |
| `POST /api/services/{start,stop,restart}` | 启停（start/restart 异步即返，stop 同步轮询 10s） |
| `POST /api/services/delete` | SCM 注销 |
| `POST /api/services/deploy` | `sc create` 注册 + config 加条目 |
| `POST /api/services/start-all` | 后台按序启动（读 `script.json` start_order） |
| `POST /api/services/update` | multipart 上传 exe/pdb 热更新（停→替换→启） |

### 其他

| 接口 | 用途 |
|---|---|
| `GET /api/config` | config.json 全文 |
| `GET\|POST /api/spideorder/{get,save,execute}` | spideOnlineLog 编排（config 读写 + 后台执行） |
| `GET\|POST /api/templates/{get,save,delete}` | 模板库（SQLite，复用 legacy templates.db） |
| `GET /api/fetch-title?url=` | URL 标题抓取 |
| `GET /health` | 健康检查 → `ok` |

---

## 常用脚本

| 脚本 | 用途 |
|---|---|
| `start.py` | **跨平台入口**（win/mac 共用）。解析 `.venv` 解释器 → 启动 `run.py`，argv 透传 |
| `run.py` | **前台 launcher**。键盘循环（`r`重载 / `q`退出 / `s`状态 / `h`帮助）+ launcher 控制 socket（`\\.\pipe\infoserver_ctl`） |
| `main.py` | **纯启动器**（无 HTTP）。读 config → `ServiceGroupManager.start_all` → 阻塞等 SIGINT → stop_all。开服务级控制 socket（`\\.\pipe\infoserver_svc`）供 `services`/`restart`/`swap_exe` |
| `service_manager.py` | **Job Object 托管核心**。Win ctypes 绑 Job Object（父退出→子终止）；`ManagedService` 封装启停/健康检查/auto_restart/崩溃退避 |
| `ctl_client.py` | **控制面 CLI**。JSON-RPC 2.0 over `multiprocessing.connection`，`--socket ctl/svc` 分流（见上） |
| `serviceGroup/serviceServer/build.bat` | Rust **构建+部署**。`cargo build --release` + cp `target/release/service-server.exe` → 项目根 `service-server.exe`（config.yaml 指向根 exe） |
| `serviceGroup/serviceServer/spideOnlineLog.py` | **线上日志抓取**。`--source oss`，路径 `{service}/{hostID}/{log|Record}/{svc}-{YYYYMMDD}{HHMMSS}-{type}.zip`；CPP 堡垒机日志排查用 |
| `quickstart.py` / `startup.py` | 旧入口（保留兼容），推荐用 `start.py` |

---

## Rust exe 热更新（service-server）

改 `serviceGroup/serviceServer/src/*.rs` 后：

```bash
cd serviceGroup/serviceServer
cargo test                  # 验证 (rstest 参数化 + #[test], 当前 94 用例)
./build.bat                 # cargo build --release + cp target/release/service-server.exe .
```

让运行中 servicesvr 加载新 exe（**三选一**）：

```bash
# 路 A (首选): cwd-mcp 自动 stop+sleep2+cp+start, 规避 Windows 文件占用
cwd_infoserver_swap_exe(5000)

# 路 B: ctl_client
python ctl_client.py --socket svc swap_exe --params '{"port": 5000}'

# 路 C (手动, 不推荐): mv 运行位 exe → .bak + cp 新 exe + restart(5000)
#   (Windows 运行中 exe 可 rename 不可覆盖; .bak 留回滚但需手动清)
```

> **勿用裸 `cp` 覆盖运行中 exe**：Windows 文件占用 + O_CREAT 保留 inode 风险。swap_exe 是唯一已证实杠杆。

---

## 项目结构

```
infoServer/
├── start.py / run.py / main.py            # 跨平台入口 + 前台 launcher + 纯启动器
├── ctl_client.py / service_manager.py      # 控制面 CLI + Job Object 托管
├── config.yaml                            # 子服务开关板 (单一真相源)
├── serviceGroup/
│   ├── parlanceChat/                      # :5001 局域网聊天/文件共享
│   │   ├── main.py / routes.py / chat_manager.py / database.py / file_handler.py
│   │   └── static/ (index.html / script.js / style.css)
│   ├── serviceServer/                     # :5000 Rust 工具服务 (本 README 重点)
│   │   ├── src/ (main.rs + routes/ + path_map.rs + path_check.rs + encoding.rs + backup.rs + ...)
│   │   ├── Cargo.toml / build.bat
│   │   ├── spideOnlineLog.py
│   │   └── AGENTS.md                      # Rust 架构/构建/测试详
│   ├── serviceServer-legacy/              # :5099 旧 Flask (被 Rust 反代, 渐进瘦身)
│   ├── statisticServer/                   # :5002 DeepSeek 代理统计
│   └── debugRelay/                        # :5003 真机调试中继
├── tests/                                 # launcher 控制面测试
└── docs/ / skills/ / QA.md
```

---

## parlanceChat (:5001) — 聊天/文件共享

- **实时聊天**：SSE 推送，文本/文件/打包发送
- **文件传输**：拖拽/粘贴，多文件自动 ZIP，断点续传（HTTP Range）
- **昵称/撤回/清空/用户筛选**
- **7 套主题**（CSS 变量 `html[data-theme]` 切换，按 IP 持久化）：兰亭信传 / 简约 / 珊瑚宫心海 / 流萤·萨姆 / 芙宁娜·歌剧院 / 深海潮汐 / 天才俱乐部
- **响应式**（手机触摸适配）

壁纸资源（珊瑚宫心海/流萤/芙宁娜）: <https://pan.baidu.com/s/5JXkz0LTTf2X13pVF2ij5_A>，下载后放 `serviceGroup/parlanceChat/style/{kokomi,firefly,furina}/`。

自定义主题：在 `static/style.css` 加 `html[data-theme="你的主题"] { --cn-* : ...; }` 变量块 + `static/script.js` 的 `THEMES`/`THEME_NAMES` 数组加条目。

聊天 REST API：`/api/messages*` / `/api/download/{id}` / `/api/events`(SSE) / `/api/theme` / `/api/profile` / `/api/users` / `/api/health`。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 启动器 | Python 3 + PyYAML + Windows Job Object (ctypes) + multiprocessing.connection |
| parlanceChat / debugRelay / statistic | FastAPI + uvicorn + SSE + aiofiles + SQLite |
| serviceServer | Rust 1.x + axum 0.7 + tokio + encoding_rs + rusqlite + windows crate (SCM/IO/IP Helper) |
| RoleManager（外部 skillrepo 仓） | Rust，role MCP (stdio) + WebReader HTTP (5090) |
