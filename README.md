# roleManager — AI 角色开发指南仓库

集中管理多角色开发规范、知识笔记和工作流文档，配合 HTTP Notes API 实现 AI 与人类开发的统一协作。

## 项目结构

```
roleManager/
├── COMMON.md                  # 全局公共配置与规则
├── RoleManager/               # Notes API 服务器 (Rust/Actix)
├── <Role>/                    # 角色目录 (CP-DEV-xzmp, CPP-GameSVR-DEV-xzmp, ...)
│   ├── L0_Index.md            # 角色全局索引
│   ├── L1_<Module>.md         # 模块地图
│   ├── L2_<Feature>.md        # 深度逻辑
│   └── doc/                   # 原型/实现文档
├── common/                    # 共享文档
├── WorkFlow/                  # 角色工作流
└── QuickStartForRole/         # AI 角色快速启动模板
```

支持角色: CP-DEV-xzmp, CPP-GameSVR-DEV-xzmp, Creator-Client-DEV-xzmp, LUA-Client-DEV-xzmp, ChangData-Seeker, Service-Svr-Dev

## QuickStart

### 1. 工作区准备

**方式一（以 当前项目目录 为工作区）**：直接启动 agent（Claude Code / 其他 AI agent）即可，无需额外配置。

**方式二（以其他目录 为工作区）**：将 `QuickStartForRole/CLAUDE.md` 复制到目标工作区下，然后启动 agent。

### 2. 角色身份确认

agent 启动后会自动引导你描述角色身份（如 CP-DEV-xzmp、CPP-GameSVR-DEV-xzmp 等）。你也可以直接修改 `CLAUDE.md` 第一行的角色名称写死，以跳过确认环节。

角色确认后，agent 会自动:
1. 加载 `COMMON.md` 获取全局规则
2. 加载对应角色的 `L0_Index.md`（角色全局索引）
3. 后续按需查看 L1 / L2 / L3 等更低层级的文档

### 3. Notes API 服务

agent 确认角色身份后会自动启动接口服务（端口 5080），你也可以手动启动:

```bash
./RoleManager.exe
# 默认监听 0.0.0.0:5080，可通过环境变量 ROLE_MANAGER_PORT 修改端口
```

验证:

```bash
curl http://127.0.0.1:5080/api/a2a/health
# 预期: {"service":"RoleManager","success":true,"version":"0.1.0"}
```

### 4. agent 工作流程

1. **先查阅文档**：按 L0 → L1/L2 → L3 渐进式加载，避免全量扫描
2. **再阅读代码**：文档不足时读取源码
3. **回写文档**：代码查阅完毕后，如发现文档过时或缺失，告知 agent 需要手动更新回文档（agent 不会擅自改写文档）

### 5. Notes API

所有读写操作均通过 HTTP API 调用：

| 操作 | 方法 | 路径 | 自动 Git 提交 |
|------|------|------|:---:|
| 列表 | GET | `/api/a2a/list?path=` | ❌ |
| 读取 | GET | `/api/a2a/get?path=` | ❌ |
| 创建 | POST | `/api/a2a/create` | ✅ |
| 更新 | POST | `/api/a2a/update` | ✅ |
| 删除 | POST | `/api/a2a/delete` | ✅ |
| 历史 | GET | `/api/a2a/history?path=` | ❌ |
| 版本 | GET | `/api/a2a/version?path=&hash=` | ❌ |

API 基础地址: `http://127.0.0.1:5080`

### 6. 笔记层级说明

| 层级 | 文件名 | 用途 |
|------|--------|------|
| L0 | `L0_Index.md` | 角色全局索引，tech stack、职责、路径索引 |
| L1 | `L1_<Module>.md` | 模块地图，模块边界、文件摘要、术语表 |
| L2 | `L2_<Feature>.md` | 深度逻辑，状态机、数据结构、陷阱 |
| L3 | `L3_<Feature>.md` | 实现级文档，从实现 doc 生成 |

## 添加新角色

告知 agent「需要创建新角色」，agent 会参考已有角色的目录结构进行设计。每个角色需要描述:

- **工作区路径**：该角色依赖的代码仓库路径
- **工作职能**：该角色负责的业务范围和技术栈
