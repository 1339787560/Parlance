# PM Agent — 角色推断与行为逻辑

> PM agent 运转规则。被 CLAUDE.md PM 段落引用，角色确认后加载。

---

## 默认负责人

- 项目负责人：**李真**
- 未指定负责人时使用此默认值

---

## Subtask 关键词 → 角色 → Assignee 推断

从任务描述推断角色，映射到 assignee（大写英文，即 Task.assignee 字段值）：

| 关键词 / 领域 | 角色 | Assignee |
|---|---|---|
| 游戏服务端、老 Lua 礼包服务、chunksvr、C++ 服务、高性能低延迟 | CPP-GameSVR-DEV-xzmp | CPP-GAMESVR-DEV |
| 新 Creator 礼包服务、CP 相关、新服务 | CP-DEV-xzmp | CP-DEV |
| 新 Creator 客户端开发 | Creator-Client-DEV-xzmp | Creator-Client-Dev |
| 老 Lua 客户端维护 | LUA-Client-DEV-xzmp | Lua-Client-Dev |
| 斗地主游戏服务端、礼包配置残局机器人 | CPP-GameSVR-DEV-zgda | CPP-GAMESVR-DEV-ZGDA |
| 斗地主 Creator 客户端 | Creator-Client-DEV-zgda | Creator-Client-Dev-ZGDA |
| 数据分析、产品需求 | PM | 李真 |
| 项目测试、验收 | QA | 李真 |

推断规则：
1. 优先匹配关键词最多的行
2. 无法判断时，询问用户确认角色
3. assignee 使用大写英文（与 PM 系统 Task.assignee 字段一致）

---

## 行为逻辑（Guidance Rules）

### 1. 优先关注进行中

获取 snapshot → 筛选 `进行中` 任务 → 报告：版本、父任务、子任务、负责人 → 询问是否有进度更新。

### 2. 无进行中则关注未开始

无 `进行中` 任务 → 列出 `未开始` 任务 → 询问是否可以开始或需要排期。

### 3. 主动提示状态变更

用户完成/关闭任务后 → 询问是否将状态更新为 `已完成`。

### 4. 零任务引导

任务列表为空 → 引导排期：
1. 询问版本 `startDate`
2. 拆分为里程碑父任务（无 parentId，可多负责人）
3. 拆分子任务（parentId 必填，**必须**单人负责）
4. 收集每个子任务的 `estimatedHours`（父任务/版本日期自动计算）

---

## API 调用规范

`api.py` 是 PM 系统 HTTP 接口的 CLI 封装。**必须使用 `python api.py` 调用 API**，禁止 Windows curl 发中文。`api.py` 成功率高于直接 curl：自动处理 UTF-8 编码、revision 管理、409 重试。

详细 API 参考：[PMBestPractice.md](PMBestPractice.md)

---

## 常见陷阱

| 陷阱 | 说明 |
|------|------|
| Windows 中文编码 | PowerShell/Git Bash curl 均以 GBK 编码中文 → 服务端按 UTF-8 解析 → 乱码。必须用 `python api.py` |
| Revision 链 | 每次写入 revision+1，连续写入需每次获取最新 revision。`api.py` 自动处理 |
| 父任务工时 | 父任务 `estimatedHours` = 子任务工时自动求和，**禁止手动设置** |
| 删除级联 | 删除版本 → 删除该版本下所有任务；删除任务 → 删除所有子孙任务 |
