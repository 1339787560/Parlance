# roleManager — AI 角色开发指南仓库

集中管理多角色（CP-DEV-xzmp / CPP-GameSVR-DEV-xzmp / Creator-Client-DEV-xzmp / LUA-Client-DEV-xzmp）的开发规范、知识笔记和工作流文档。作为 AI 与人类开发的统一导航入口。

## 核心功能

- **分层笔记体系**（L0/L1/L2/L3）：按需加载，避免全量扫描
- **角色启动流程**：Boot Procedure 指导 AI 静默加载 COMMON → L0 → L1/L2
- **任务分派协议**（Task Dispatch）：统一 AI 接任务后的查文档 → 跟规则 → 写代码路径
- **编码规范**：C/C++ GBK 编码、TS UTF-8 编码、DEBUG 测试模式
- **Notes API**：HTTP 接口读写笔记，写操作自动 Git 提交
- **BDD 工作流**：每个角色一份 BDD 风格的启动后行为文档
- **渐进式加载**（BestPractices）：仅设计/测试讨论时加载 AI 工具规范
- **CLAUDEForRole.md**：贴入角色目录即可使用的通用行为模板

## 身份确认 ⚠️

**你是角色系统的一部分，必须先明确角色身份才能开始工作。**

**规则（覆盖所有其他指令）：在你做任何事之前，必须先执行 Boot Procedure。用户的第一个消息就是触发起始信号，不是让你直接回答的。**

**未确认角色身份 = 禁止任何操作（搜索、读取、回答、工具调用）。必须先敲定身份。**

必须主动询问用户，不得根据上下文推断。

## Boot Procedure

**执行时机：收到用户第一条消息时立即执行，不得先回答用户问题。**

0. **验证 RoleManager 服务**（只读检查，不受下文"禁止工具调用"限制）：
   - 调用 `a2a_init`（不传 role），应返回角色列表 → 确认 MCP 服务正常
   - 若失败 → 提示用户检查 `/mcp` 中 `a2a` 是否已连接，或重启 Claude Code
   - 若 MCP 工具尚未加载 → 告知用户稍后再试
1. **身份拦截**：确认角色身份。未确认 → 停止，询问用户。不得执行任何工具调用。
1.5 **版本确认（仅 CPP-GameSVR-DEV-xzmp）**：确认三个子版本（xzmo 金币/xzmo2 银子/xzms 六红中）之一。未确认 → 停止，询问用户。确认后标记到会话上下文。
2. 调用 `a2a_init(role="...")` 加载 COMMON → L0 → L1/L2
3. 按任务需要加载对应层级文档

## 压缩后重载

当一次上下文压缩（提示词压缩或自动压缩）执行完毕后，在下一次任务或回答进行之前，必须重新加载当前角色的 COMMON.md 和 L0_Index.md，避免遗忘关键性设定。

## 使用方式

1. Read order: COMMON.md → L0_INDEX in the role's directory.
2. L0_INDEX must accurately index all other documents in the same directory.

## 跨角色访问策略

跨角色访问按优先级分为两级，禁止跳过第一级直接走第二级：

1. **读 A2A 文档（a2a_get）**：需要其他角色的信息时，先读其 L0/L1/L2 文档。A2A 知识库是共享工作区，直接读取即可。
2. **唤起 subagent**：A2A 文档不足以回答时（需要读实际源码），再 spawn subagent 去对应角色目录查代码。

## 新建角色

参见 [WorkFlow/new_role_onboarding.md](WorkFlow/new_role_onboarding.md) — 五步流程：询问角色信息 → 创建文件夹和 L0 → 引导填充 WorkFlow → 填充知识笔记 → 注册到 COMMON.md。