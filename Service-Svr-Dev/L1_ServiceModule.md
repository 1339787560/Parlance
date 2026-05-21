# L1 - 服务管理模块

> 文件：`Service.py`（~924 行）

---

## 概述

Service.py 是服务管理的核心模块，提供 Windows 游戏服务的完整生命周期管理：
进程检测 → 服务启停 → 部署卸载 → 文件热更新 → 状态聚合 → SVN 操作 → 文件读写

---

## 核心数据结构

```python
service_status = {}  # 全局状态字典，threading.Lock 保护
lock = threading.Lock()
```

状态值：`运行中` / `未运行` / `未部署` / `启动中` / `停止中` / `启动失败` / `停止失败`

---

## 进程管理

### `get_process_id_by_exe(exe_name, exe_path=None)` → pid | None
四级模糊匹配策略：
1. 精确匹配进程名 → 精确匹配 exe 路径
2. 模糊匹配进程名（去掉扩展名） → 路径包含
3. 路径中包含 exe 文件名
4. 如提供 exe_path 则进一步校验目录

### `get_ports_by_pid(pid)` → [port, ...]
通过 psutil 获取进程 LISTEN 状态的端口列表，去重排序。

---

## Windows 服务生命周期

### 启动 `start_service(name, type_name, exe_name)`
1. 检查服务是否已在运行（`win32serviceutil.QueryServiceStatus`）
2. 检查服务是否已安装，未安装则 `InstallService`
3. `StartService` → 轮询最多 10s 确认运行状态
4. 更新 `service_status` 字典
- 路径格式：`{abspath}/{name}/{type}/{exe_name}`
- 服务显示名：`同城游_{name}_{type}`

### 停止 `stop_service(name, type_name, exe_name)`
分两种策略：
- **robot_tool / proxy_game / proxy_room / proxy_assist**: 使用 `stop_service_pywin32`（Windows 服务管理）
- **其他**: 使用 `stop_service_quick`（直接 terminate/kill 进程）

### 部署 `deploy_service(name, type_name, exe_name)`
1. 写入 config.json service 配置
2. 通过 `sc create` 注册 Windows 服务

### 删除 `delete_service(name, type_name)`
1. 停止服务
2. 卸载 Windows 服务（`RemoveService`）
3. 从 `service_status` 移除

### 热更新 `update_service_file(name, type_name, exe_name, new_exe_content, new_pdb_content)`
停止 → 替换 .exe + .pdb → 重启（间隔 2s）

---

## 状态聚合

### `get_all_service_status()` → dict
遍历 config.json 中的所有服务，逐项检查：
1. 是否在 `service_status` 中有记录 → 区分"已部署"和"未部署"
2. 是否安装为 Windows 服务 → 检查是否存在服务项
3. 进程是否存在 + 路径是否匹配 → 确认"运行中"
4. 如运行中则进一步获取端口信息
5. 返回格式：`{service_id: {status, type, exe, name, display_name, path, exe_path, ports}}`

---

## SVN 操作

### `get_svn_status()` → (is_latest, message)
执行 `svn status -u --non-interactive`，解析输出：
- 存在 `*` 开头行 → 有未同步更改
- 存在 `!` 开头行 → 有缺失文件
- 第二列有 `*` → 有远程变更

### `update_svn()` → (success, message)
执行 `svn update --non-interactive`，解析 `Updated to revision` / `At revision`

---

## 文件工具

### `read_file_content(file_path, encoding='utf-8')` → (content, actual_encoding)
多编码回退策略：指定编码 → UTF-8 → GBK → UTF-16-LE → UTF-16-BE → latin-1(errors='ignore')

### `save_file_content(file_path, content, encoding='utf-8')`
先备份为 `.backup` → 写入 → 写入成功删备份，写入失败恢复备份

---

## 配置依赖

- **config.json**: `abspath`（服务根目录）、`svnPath`、`service`（服务定义）、`spideOrder`（爬虫命令）
- **script.json**: `scripts[{name, sequence}]` 启动序列
