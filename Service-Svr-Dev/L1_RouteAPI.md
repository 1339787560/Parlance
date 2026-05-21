# L1 - REST API 路由模块

> 文件：`CustomRoute/__init__.py` + `ServiceRoute.py`（~2552 行） + `SequenceRoute.py` + `BaseRoute.py` + `TemplateDB.py`

---

## 路由架构

```
CustomRoute/
├── __init__.py      ← 创建 Flask app（static_folder=../src），导入所有路由模块
├── BaseRoute.py     ← 主页路由（/、/sequence）
├── ServiceRoute.py  ← 全部业务 API（~2500 行，核心端点）
├── SequenceRoute.py ← 启动序列管理
├── TemplateDB.py    ← SQLite 模板存储
└── templates/       ← 9 个 HTML 页面
```

Flask app 在 `__init__.py` 中初始化，所有路由通过 `@app.route()` 注册。

---

## 请求/响应规范

- **成功响应**: `jsonify({'success': True, ...})` + HTTP 200
- **业务失败**: `jsonify({'success': False, 'message': '...'})` + HTTP 200
- **参数错误**: HTTP 400
- **路径拒绝**: HTTP 403
- **资源不存在**: HTTP 404
- **异常**: HTTP 500 + `jsonify({'error': str(e)})`
- 耗时操作（服务启停、执行命令）均在新线程中执行，避免阻塞 HTTP 响应

---

## 主要 API 分组

### 服务管理（ServiceRoute.py:18-121）
| 端点 | 方法 | 关键逻辑 |
|------|------|----------|
| `/api/services/status` | GET | 调用 `Service.get_all_service_status()`，检查进程 + 端口 + Windows 服务状态 |
| `/api/services/start` | POST | 新线程调用 `Service.start_service()`，先检查是否已在运行 |
| `/api/services/stop` | POST | 调用 `Service.stop_service()`，robot/proxy 类型用 pywin32，其他直接杀进程 |
| `/api/services/deploy` | POST | 注册为 Windows 服务 + 写入 config.json |
| `/api/services/delete` | POST | 停止 + 卸载 Windows 服务 + 从配置移除 |
| `/api/services/update` | POST | 上传 exe+pdb → 停止 → 替换文件 → 启动（文件名校验） |
| `/api/services/start-all` | POST | 按 script.json 顺序逐个启动 |

### 配置编辑（ServiceRoute.py:818-1275）
- 列出/读取/保存服务目录下的 .ini / .json / .lua 文件
- 路径安全检查：只允许访问运行中服务的目录
- 分支管理：创建 `{name}_{branch}.{ext}` → 切换到分支 → 删除分支
- 切换分支时自动备份原文件到 `remove/` 目录，内容验证通过后才删除备份
- 编码自动检测（UTF-8 / GBK / UTF-16 / latin-1 fallback）

### 运营工具（ServiceRoute.py:183-368）
- **金币设置**: 通过 subprocess 调用 `RobotToolD.exe`，支持 single/multi 模式，超时 3s 自动杀进程
- **TQVIP 设置**: protobuf 序列化写入游戏数据库，支持批量用户
- **周卡/月卡**: protobuf 序列化，`timeUtil` 计算起止时间

### AI 管理（ServiceRoute.py:1677-1936）
- 两个 API 供应商预配置：mdproxy（tcy365）和 deepseek
- 读写 `~/.claude/settings.json` 切换供应商/模型
- Benchmark 压测：通过 `CommonTools.agent.speedTest` 执行，2 小时间隔自动调度（当前注释关闭）

### AI 反向代理（ServiceRoute.py:2024-2092）
- `/api/ai-proxy/<path>` 透明转发到 AI 聚合平台（aiapi.tcy365.net:82）
- 自动注入当前 Claude 模型到请求体 `model` 字段
- 流式响应透传

### RAG 知识库（ServiceRoute.py:2434-2552）
- ChromaDB 向量检索引擎，支持多嵌入模型切换
- 飞书文档同步（feishu2md 工具导出）
- SSE 流式问答响应（`text/event-stream`）

### A2A 文件管理（ServiceRoute.py:2095-2432）
- 路径安全校验（`get_a2a_relative_path()` 防止路径穿越）
- 每次写操作自动 Git commit
- 文件列表仅暴露 .md / .py / .json 和目录

### 序列管理（SequenceRoute.py）
- script.json 格式：`{scripts: [{name, sequence: [{name, type, exe}], created_at}]}`
- 执行时逐个启动，间隔 2 秒，失败则中断返回

### 系统工具
| 端点 | 说明 |
|------|------|
| `/api/serverstatus/get` | psutil 获取 CPU/内存/磁盘/网络/进程数 |
| `/api/serverstatus/stop` | 延迟 1s 后 `os._exit(0)` |
| `/api/serverstatus/restart` | subprocess 启动新 main.py 后退出 |
| `/api/system/restart` | 多重尝试重启 OS（shutdown / PowerShell / wmic） |
| `/api/fetch-background` | Playwright 爬取背景图 + 大小比对去重 + 本地缓存 |
| `/api/fetch-metadata` | 抓取 URL 标题 + 图标，本地缓存图标 |
