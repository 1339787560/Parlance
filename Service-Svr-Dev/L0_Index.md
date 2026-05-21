# L0 全局索引 - serviceSvrDev

> 综合体工具工程师工作区全局索引

---

## 核心职责

负责编写 Python Flask + 前端 HTML/CSS/JS，提供 HTTP API 工具和可视化工具。
管理游戏服务的部署、启停、配置修改、日志抓取，以及 AI 代理和知识库问答系统。

---

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12 | 后端语言 |
| Flask | Web 框架，提供 REST API |
| Flask-CORS | 跨域支持 |
| HTML + CSS + JS | 前端页面（9 个模板） |
| SQLite | 模板存储数据库 |
| MySQL (mysql-connector) | 游戏数据库连接 |
| Redis | 缓存（预留） |
| protobuf | TQVIP/月卡数据序列化 |
| psutil | 系统/进程监控 |
| pywin32 | Windows 服务管理 |
| Playwright | 背景图自动抓取 |
| ChromaDB + sentence-transformers | RAG 知识库向量检索 |
| MCP (Model Context Protocol) | A2A 文件管理 AI 工具 |
| Git | A2A 版本控制 |
| SVN | 游戏服务代码版本控制 |
| subprocess | 调用 RobotToolD.exe 等外部工具 |

---

## 工作范围

### 1. 游戏服务管理
- Windows 服务启停（`start_service` / `stop_service` / `deploy_service` / `delete_service`）
- 服务热更新（上传 .exe + .pdb 替换文件，自动重启）
- 一键按序启动多服务（`script.json` 命名序列）
- 服务状态轮询（进程检测 + 端口检测）
- 覆盖 xzmo / xzmo2 / xzms / zgda / zgdb / zgdf 等多游戏项目

### 2. 在线配置编辑
- 服务运行时 .ini / .json / .lua 文件在线编辑
- 分支管理（创建、切换、删除配置分支）
- 文件备份与恢复
- 编码自动检测（UTF-8 / GBK / UTF-16）

### 3. 系统运维工具
- 服务器状态监控（CPU / 内存 / 磁盘 / 网络 / 进程/线程数）
- 系统重启（Windows shutdown / PowerShell / wmic 多重尝试）
- SVN 状态检查与更新
- 日志在线爬取（spiderOnlineLog.py，正则匹配抓取错误日志）

### 4. 游戏运营工具
- 金币设置（`setSingleGold` / `setMultiGold`，通过 RobotToolD.exe）
- 荣耀特权设置（TQVIP，protobuf 序列化读写数据库）
- 周卡/月卡设置（TQMonthCard）

### 5. AI 代理管理
- API 供应商切换（mdproxy / deepseek）
- Claude 模型切换（settings.json 读写）
- AI API 反向代理（转发到 AI 聚合平台）
- AI 模型 Benchmark 压测与结果分析

### 6. RAG 知识问答
- ChromaDB 向量索引构建与管理
- 嵌入模型切换（多模型支持）
- 飞书文档同步（feishu2md）
- SSE 流式问答接口

### 7. A2A 文件管理系统
- A2A 文件 CRUD（列表/读/写/删）
- Git 版本控制（每次写操作自动 commit）
- 历史版本回溯
- MCP Server 封装（供 Claude Code 直接调用）

### 8. 前端页面
| 页面 | 路由 | 功能 |
|------|------|------|
| 主面板 | `/` | toolbar 聚合入口 |
| 服务序列 | `/sequence` | 启动序列管理 |
| 服务状态 | `/serverstatus` | 系统/进程实时监控 |
| 充值配置 | `/deposit` | 金币/特权/月卡设置 |
| 在线配置 | `/onlineConfigModify` | 运行时配置文件编辑 |
| 定时文件 | `/fileontimer` | 定时文件浏览/下载 |
| AI 管理 | `/ai-manager` | 供应商/模型切换 + Benchmark |
| A2A 管理 | `/a2a-manager` | A2A 文件浏览/编辑 |
| RAG QA | `/rag-qa` | 知识库问答 |

---

## 项目目录结构

```
serviceServer/
├── main.py                 ← 启动入口（Flask 0.0.0.0:5000）
├── Service.py              ← 服务管理核心（Windows 服务 + 进程 + SVN + 文件）
├── JsonConfigParser.py     ← config.json / script.json 读写
├── spideOnlineLog.py       ← 日志爬虫（正则抓取错误日志）
├── mcp_a2a_server.py       ← A2A MCP Server（Claude Code 工具集成）
├── config.json             ← 服务配置、toolbar、spideOrder
├── script.json             ← 启动序列配置
├── requirements.txt        ← Python 依赖
│
├── CustomRoute/            ← Flask 路由模块
│   ├── __init__.py         ← Flask app 初始化 + 路由导入
│   ├── BaseRoute.py        ← 主页 /sequence 路由
│   ├── ServiceRoute.py     ← 全部 API 路由（~2500 行）
│   ├── SequenceRoute.py    ← 启动序列 API
│   ├── TemplateDB.py       ← SQLite 模板存储
│   └── templates/          ← 9 个 HTML 模板
│       ├── index.html, sequence.html, ServerStatus.html,
│       ├── deposit.html, onlineConfigModify.html,
│       ├── FileOnTimer.html, AIManager.html,
│       ├── A2AManager.html, ragQA.html
│
├── CommonTools/            ← 公共工具库
│   ├── xzmpDB/             ← 数据库工具
│   │   ├── DBConnector.py  ← MySQL 连接器
│   │   ├── TQVIP.py        ← 荣耀特权 + 周卡/月卡管理器
│   │   └── tqvip_pb2.py    ← protobuf 定义
│   ├── agent/              ← AI 工具
│   │   ├── anthropic_adapter.py  ← Anthropic API 适配
│   │   ├── chat_loop.py          ← AI 对话循环
│   │   └── speedTest.py          ← Benchmark 压测
│   └── ragKnowledge/       ← RAG 知识库
│       ├── rag_engine.py         ← 检索引擎（ChromaDB）
│       ├── document_processor.py ← 文档处理
│       ├── config.py             ← 模型配置
│       ├── scheduler.py          ← 飞书同步调度
│       ├── evaluation.py         ← 评估工具
│       └── rebuild_index.py      ← 索引重建
│
├── src/                    ← 静态资源
│   ├── A2AFile/            ← A2A 文件存储（独立 Git 仓库）
│   ├── cache/              ← 缓存（背景图缓存、图标缓存）
│   ├── extern/             ← 外部数据（friendlink.json）
│   └── background/         ← 用户背景图
│
├── exeDir/                 ← 外部可执行文件
│   ├── RobotToolD.exe      ← 金币设置工具
│   └── feishu2md/          ← 飞书文档导出工具
│
├── FileOnTimer/            ← 定时文件存放目录
├── tests/                  ← 测试
│   ├── test_a2a.py
│   └── test_rag_flow.py
└── docs/
    └── a2a-file-api.md     ← A2A API 文档
```

---

## API 总览

| 分类 | 端点 | 方法 | 说明 |
|------|------|------|------|
| **服务管理** | `/api/services/status` | GET | 全部服务状态 |
| | `/api/services/start` | POST | 启动服务 |
| | `/api/services/stop` | POST | 停止服务 |
| | `/api/services/deploy` | POST | 部署服务 |
| | `/api/services/delete` | POST | 删除服务 |
| | `/api/services/update` | POST | 热更新（上传 exe+pdb） |
| | `/api/services/start-all` | POST | 一键启动全部 |
| **SVN** | `/api/svn/status` | GET | SVN 状态检查 |
| | `/api/svn/update` | POST | SVN 更新 |
| **运营工具** | `/api/set-gold` | POST | 设置金币 |
| | `/api/set-tqvip` | POST | 设置荣耀特权 |
| | `/api/set-weekcard` | POST | 设置周卡 |
| | `/api/set-monthcard` | POST | 设置月卡 |
| **配置编辑** | `/api/config/files` | GET | 列出服务配置文件 |
| | `/api/config/file/content` | GET | 读取配置文件 |
| | `/api/config/file/save` | POST | 保存配置文件 |
| | `/api/config/file/branches` | GET | 获取分支列表 |
| | `/api/config/file/create_branch` | POST | 创建分支 |
| | `/api/config/file/switch_branch` | POST | 切换分支 |
| | `/api/config/file/remove_branch` | DELETE | 删除分支 |
| | `/api/config/services/running` | GET | 运行中服务列表 |
| | `/api/config` | GET | 获取完整 config.json |
| **SpideOrder** | `/api/spideorder/get` | GET | 获取爬虫配置 |
| | `/api/spideorder/save` | POST | 保存爬虫配置 |
| | `/api/spideorder/execute` | POST | 执行爬虫命令 |
| **系统监控** | `/api/serverstatus/get` | GET | 系统 + 进程状态 |
| | `/api/serverstatus/stop` | POST | 停止 Flask 服务 |
| | `/api/serverstatus/restart` | POST | 重启 Flask 服务 |
| | `/api/system/restart` | POST | 重启操作系统 |
| **AI 管理** | `/api/benchmark/latest` | GET | 最新 Benchmark |
| | `/api/benchmark/all` | GET | 全部 Benchmark |
| | `/api/benchmark/trigger` | POST | 触发压测 |
| | `/api/claude/model` | GET/POST | 获取/设置模型 |
| | `/api/claude/provider` | GET/POST | 获取/切换供应商 |
| | `/api/ai-proxy/<path>` | 任意 | AI API 反向代理 |
| **A2A** | `/api/a2a/list` | GET | 文件列表 |
| | `/api/a2a/get` | GET | 读取文件 |
| | `/api/a2a/create` | POST | 创建文件 |
| | `/api/a2a/update` | POST | 修改文件 |
| | `/api/a2a/delete` | POST | 删除文件 |
| | `/api/a2a/history` | GET | Git 历史 |
| | `/api/a2a/version` | GET | 历史版本 |
| **RAG** | `/api/rag/status` | GET | 索引状态 |
| | `/api/rag/index` | POST | 重建索引 |
| | `/api/rag/documents` | GET | 文档列表 |
| | `/api/rag/query` | GET | 流式问答 |
| | `/api/rag/models` | GET | 模型信息 |
| | `/api/rag/model/switch` | POST | 切换模型 |
| | `/api/rag/sync` | POST | 飞书同步 |
| | `/api/rag/sync/status` | GET | 同步状态 |
| **序列管理** | `/api/script/get-all` | GET | 所有序列 |
| | `/api/script/save` | POST | 保存序列 |
| | `/api/script/execute` | POST | 执行序列 |
| | `/api/script/execute/<name>` | POST | 按名执行序列 |
| **其他** | `/api/templates/save` | POST | 保存模板 |
| | `/api/templates/get` | GET | 获取模板 |
| | `/api/templates/delete` | POST | 删除模板 |
| | `/api/fetch-background` | GET | 抓取背景图 |
| | `/api/friendlinks` | GET | 友链列表 |
| | `/api/fetch-metadata` | GET | 抓取 URL 元数据 |
| | `/api/fetch-title` | GET | 抓取页面标题 |
| | `/api/fileontimer/list` | GET | 定时文件列表 |
| | `/api/fileontimer/download` | GET | 下载定时文件 |

---

## 架构规约

1. **路由分离**：路由代码在 CustomRoute/，Flask app 实例在 `CustomRoute/__init__.py`
2. **工具复用**：通用工具放在 CommonTools/ 下按子模块组织
3. **服务管理**：Service.py 管理 Windows 服务生命周期，API 层通过 ServiceRoute.py 暴露
4. **前端**：HTML 模板在 CustomRoute/templates/，静态文件在 src/
5. **版本控制**：Git（A2A 系统）+ SVN（游戏服务代码）
6. **A2A 维护**：A2A 文件系统在 `src/A2AFile/`，独立 Git 仓库，MCP Server 封装供 Claude Code 调用

---

## 文档索引

| 层级 | 文档 | 说明 |
|------|------|------|
| L1 | [L1_RouteAPI.md](L1_RouteAPI.md) | REST API 端点参考、请求/响应格式 |
| L1 | [L1_ServiceModule.md](L1_ServiceModule.md) | 服务管理核心模块详解 |
| L1 | [L1_CommonTools.md](L1_CommonTools.md) | 数据库、AI、RAG 工具库概览 |
| L2 | — | 故障验证文档 |

---

## 协作角色

- **gamesvrDev** - 游戏服务相关问题
- **clientDev** - 客户端相关问题
- **CPDev** - 礼包服务相关问题

---

## 注意事项

- 负责维护 A2A Agent 协作系统（`src/A2AFile/`）
- 仅能通过 HTTP 接口阅览 roleManager 下的内容
- ServiceRoute.py（~2552 行）为最大文件，承载绝大部分 API 逻辑
- config.json 控制 toolbar 按钮显示、服务定义、spideOrder、configHide
