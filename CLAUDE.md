# A2AFile — AI 角色开发指南仓库

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

**未确认角色身份 = 禁止任何操作（搜索、读取、回答、工具调用）。必须先敲定身份。**

可主动询问用户提供，或根据上下文推断。未确认前不得执行任何 Read/Grep/Glob/Agent，避免过度增大上下文。

## Boot Procedure

0. **身份拦截**：确认角色身份。未确认 → 停止，询问用户。不得执行任何工具调用。
1. Load COMMON → L0 → L1/L2（按角色目录）
2. 按任务需要加载对应层级文档

## 压缩后重载

当一次上下文压缩（提示词压缩或自动压缩）执行完毕后，在下一次任务或回答进行之前，必须重新加载当前角色的 COMMON.md 和 L0_Index.md，避免遗忘关键性设定。

## 使用方式

1. Read order: COMMON.md → L0_INDEX in the role's directory.
2. L0_INDEX must accurately index all other documents in the same directory.

## 新建角色

参见 [WorkFlow/new_role_onboarding.md](WorkFlow/new_role_onboarding.md) — 五步流程：询问角色信息 → 创建文件夹和 L0 → 引导填充 WorkFlow → 填充知识笔记 → 注册到 COMMON.md。