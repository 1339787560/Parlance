# Claude Code Hooks 最佳实践方案

> 基于 CCHooks.md 官方参考文档提炼。覆盖配置架构、事件选择、脚本编写、安全与调试。

---

## 一、配置层级选择

| 位置 | 范围 | 可提交 | 适用场景 |
|---|---|---|---|
| `~/.claude/settings.json` | 所有项目 | 否 | 个人偏好、全局安全规则 |
| `.claude/settings.json` | 单个项目 | 是 | 团队共享规则、项目级 lint |
| `.claude/settings.local.json` | 单个项目 | 否 | 本地开发环境配置 |
| 托管策略 | 组织 | 是 | 企业强制策略（`allowManagedHooksOnly`） |

**原则**：团队协作规则 → `settings.json`；个人/敏感配置 → `settings.local.json`；企业管控 → 托管策略。

---

## 二、Hook 事件选择决策树

### 每会话一次（启动/结束）

| 事件 | 用途 | 关键点 |
|---|---|---|
| `SessionStart` | 加载开发上下文、设置环境变量 | stdout 直接作为 Claude 上下文；`CLAUDE_ENV_FILE` 可持久化 env |
| `Setup` | CI/脚本一次性初始化 | 仅 `--init-only` 或 `-p --init/--maintenance` 触发；不用于常规启动 |
| `SessionEnd` | 清理、日志 | 默认超时 1.5s；可用 `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` 覆盖 |

### 每轮一次（提示/停止）

| 事件 | 用途 | 关键点 |
|---|---|---|
| `UserPromptSubmit` | 注入上下文、过滤提示 | 默认超时 30s（比其他事件短）；`decision: "block"` 可阻止提示 |
| `Stop` | 防止 Claude 过早停止 | `decision: "block"` + `reason` → Claude 继续工作；检查 `stop_hook_active` 防无限循环 |
| `PreCompact` | 阻止/控制压缩 | exit 2 或 `decision: "block"` 阻止压缩；阻塞自动压缩可能导致请求失败 |

### 代理循环内（每个工具调用）

| 事件 | 用途 | 关键点 |
|---|---|---|---|
| `PreToolUse` | **最重要** — 拦截/修改工具调用 | `hookSpecificOutput.permissionDecision`: allow/deny/ask/defer；`updatedInput` 可修改参数 |
| `PostToolUse` | 后置检查、替换输出 | `updatedToolOutput` 替换 Claude 看到的输出（但工具已执行）；`additionalContext` 注入上下文 |
| `PostToolBatch` | 批量后注入上下文 | 包含完整批次 `tool_calls`；`additionalContext` 注入到下一个模型调用前 |
| `PermissionRequest` | 自动批准/拒绝权限弹窗 | `decision.behavior`: allow/deny；`updatedPermissions` 可持久化权限规则 |

### 异步/辅助事件

| 事件 | 用途 |
|---|---|
| `Notification` | 转发通知到外部服务（Slack/邮件等） |
| `SubagentStart/Stop` | 注入子代理上下文 / 控制子代理继续 |
| `FileChanged` | 监听文件变化、重新加载环境变量（`CLAUDE_ENV_FILE`） |
| `CwdChanged` | 目录切换时更新环境（direnv 集成） |
| `InstructionsLoaded` | 审计 CLAUDE.md 加载（仅可观测） |
| `ConfigChange` | 审计/阻止配置变更（`policy_settings` 不可阻止） |
| `TaskCreated/Completed` | 任务命名规范、完成门控（lint/test 必须通过） |
| `TeammateIdle` | 队友空闲质量门控 |

---

## 三、匹配器与过滤策略

### 匹配器语法

| 模式 | 评估方式 | 示例 |
|---|---|---|
| `"*"` / 空 / 略 | 匹配所有 | 每次事件都触发 |
| 纯字母数字 + `\|` | 精确字符串 | `Bash`、`Edit\|Write` |
| 含其他字符 | JS 正则表达式 | `^Notebook`、`mcp__memory__.*` |

### MCP 工具匹配

命名规则 `mcp__<server>__<tool>`。用 `.*` 匹配全部：
- `mcp__memory__.*` → memory 服务器所有工具
- `mcp__.*__write.*` → 任何服务器以 write 开头的工具

### `if` 字段精细化

`if` 使用权限规则语法，仅匹配时才 spawn hook 进程（避免无效 spawn 开销）：
- `"Bash(git *)"` → 仅 git 子命令触发
- `"Edit(*.ts)"` → 仅 TypeScript 文件触发
- 无 `if` → 匹配组内每次都运行

**最佳实践**：`matcher` 做粗筛 → `if` 做细筛。两层过滤减少不必要的进程 spawn。

---

## 四、退出代码与 JSON 输出

### 退出代码语义

| 代码 | 效果 | 适用 |
|---|---|---|
| 0 | 成功，解析 stdout JSON | 允许操作 + 精细控制 |
| 2 | 阻止错误，stderr 反馈给 Claude | 强制阻止（PreToolUse 阻止工具、UserPromptSubmit 拒绝提示） |
| 其他 | 非阻止错误，继续执行 | 不应用于策略阻止 |

**关键**：exit 1 是非阻止错误！策略阻止必须用 exit 2。JSON 输出仅在 exit 0 时解析。

### JSON 输出选择

| 方式 | 适用 | 限制 |
|---|---|---|
| 仅退出代码 | 简单允许/阻止 | 无精细控制 |
| exit 0 + JSON stdout | 结构化控制 | stdout 必须只含 JSON，shell profile 启动文本会干扰 |

**混合使用禁止**：每个 hook 选一种方式。exit 2 时 JSON 被忽略。

### JSON 核心字段

| 字段 | 默认 | 用途 |
|---|---|---|
| `continue` | true | false → Claude 完全停止处理 |
| `stopReason` | 无 | continue:false 时向用户显示的消息 |
| `systemMessage` | 无 | 向用户显示的警告 |
| `suppressOutput` | false | 从调试日志隐藏 stdout |
| `terminalSequence` | 无 | 终端通知（桌面通知/响铃），v2.1.141+ |

---

## 五、PreToolUse 决定控制（最核心）

四种决定，优先级 `deny > defer > ask > allow`：

| 决定 | 效果 | 适用场景 |
|---|---|---|
| `allow` | 绕过权限提示 | 已知安全操作自动批准 |
| `deny` | 阻止工具调用 | 危险操作拦截 |
| `ask` | 升级给用户确认 | 需人工判断的操作 |
| `defer` | 暂停等待外部 UI | Agent SDK 集成，非交互模式专用 |

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "生产数据库写入被禁止",
    "additionalContext": "当前环境为生产环境，请使用只读连接"
  }
}
```

**`updatedInput` 修改工具参数**：与 `"allow"` 或 `"ask"` 结合，在执行前改写输入。

---

## 六、脚本编写最佳实践

### 通用模板

```bash
#!/bin/bash
# 标准 hook 脚本模板

INPUT=$(cat)                           # 从 stdin 读 JSON
COMMAND=$(jq -r '.tool_input.command' <<< "$INPUT")

# 条件判断
if echo "$COMMAND" | grep -q 'rm -rf'; then
  # 策略阻止：exit 2 + stderr
  echo "Destructive command blocked: rm -rf not allowed" >&2
  exit 2
fi

# 结构化控制：exit 0 + JSON stdout
jq -nc --arg reason "Command approved" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "allow", permissionDecisionReason: $reason}}'
```

### SessionStart 注入上下文模板

```bash
#!/bin/bash
# SessionStart hook — 注入当前开发上下文

BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
CHANGES=$(git diff --stat 2>/dev/null | head -5 || echo "none")
ISSUE=$(cat .current-issue 2>/dev/null || echo "none")

jq -nc --arg branch "$BRANCH" --arg changes "$CHANGES" --arg issue "$ISSUE" \
  '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: "Current branch: \($branch)\nRecent changes: \($changes)\nActive issue: \($issue)"}}'
```

### 环境变量持久化模板

```bash
#!/bin/bash
# SessionStart hook — 设置项目环境变量

if [ -n "$CLAUDE_ENV_FILE" ]; then
  echo 'export NODE_ENV=development' >> "$CLAUDE_ENV_FILE"
  echo 'export PATH="$PATH:./node_modules/.bin"' >> "$CLAUDE_ENV_FILE"
fi

exit 0
```

### Exec 形式 vs Shell 形式

| 形式 | 条件 | 特点 |
|---|---|---|
| Exec（有 `args`） | 路径占位符、参数需精确传递 | 无 shell 标记化，路径无需引号 |
| Shell（无 `args`） | 需管道/`&&`/重定向 | shell 展开，路径需双引号 |

**Exec 形式优先**（跨平台安全，无 shell 注入风险）：

```json
{
  "type": "command",
  "command": "node",
  "args": ["${CLAUDE_PROJECT_DIR}/scripts/check.js"]
}
```

Windows 注意：`.cmd`/`.bat` 垫片不能 exec 形式。用 `node` + 脚本路径替代。

---

## 七、Hook 类型选择

| 类型 | 适用 | 性能 | 复杂度 |
|---|---|---|---|
| `command` | 通用脚本、本地检查 | 进程 spawn 开销 | 低 |
| `http` | 远程验证服务、集中审计 | 网络 IO | 中 |
| `mcp_tool` | 已有 MCP 服务器能力 | 无 spawn | 低 |
| `prompt` | LLM 判断（yes/no） | 模型调用 | 中 |
| `agent` | 需要文件/代码验证 | 多轮 + spawn | 高 |

**选择原则**：
- 简单规则 → `command`
- 远程服务 → `http`
- 已有 MCP 工具 → `mcp_tool`
- 需语义判断 → `prompt`（默认 Haiku，成本低）
- 需代码验证 → `agent`（实验性，生产慎用）

---

## 八、异步 Hooks

```json
{
  "type": "command",
  "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/run-tests.sh",
  "async": true,
  "timeout": 300
}
```

- 仅 `command` 类型支持 `async`
- 异步 hook **不能阻止操作**（触发操作已完成）
- `additionalContext` 在下一对话轮次传递给 Claude
- `asyncRewake: true` → exit 2 时唤醒 Claude（stderr 或 stdout 作为系统提醒）

**适用**：后台测试、部署通知、日志收集。**不适用**：安全拦截、策略阻止。

---

## 九、常见实战模式

### 1. 阻止危险 Bash 命令

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{
          "type": "command",
          "if": "Bash(rm *)",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-rm.sh"
        }]
      }
    ]
  }
}
```

### 2. 文件写入后自动 lint

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/lint-check.sh",
          "timeout": 30
        }]
      }
    ]
  }
}
```

### 3. Stop hook — 防止过早完成

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [{
          "type": "prompt",
          "prompt": "Check if all tasks are done. Context: $ARGUMENTS. If unfinished, respond {ok: false, reason: 'what remains'}.",
          "timeout": 30
        }]
      }
    ]
  }
}
```

### 4. Notification → 桌面通知

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "idle_prompt",
        "hooks": [{
          "type": "command",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/notify-desktop.sh"
        }]
      }
    ]
  }
}
```

### 5. PermissionRequest 自动批准安全命令

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "matcher": "Bash",
        "hooks": [{
          "type": "command",
          "if": "Bash(npm test)",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/auto-allow-npm-test.sh"
        }]
      }
    ]
  }
}
```

### 6. 任务完成门控 — lint 必须通过

```bash
#!/bin/bash
INPUT=$(cat)
TASK_SUBJECT=$(jq -r '.task_subject' <<< "$INPUT")

if ! npm run lint 2>&1; then
  echo "Lint failed. Fix lint errors before completing: $TASK_SUBJECT" >&2
  exit 2
fi

exit 0
```

---

## 十、安全规则

1. **验证输入**：hook stdin JSON 是外部数据，jq 提取后必须校验
2. **引用变量**：shell 脚本中 `"$VAR"` 不是 `$VAR`
3. **阻止路径遍历**：检查 `..` 组件
4. **使用绝对路径**：`${CLAUDE_PROJECT_DIR}` / `${CLAUDE_PLUGIN_ROOT}`，exec 形式无需引号
5. **跳过敏感文件**：`.env`、`.git/`、密钥文件不进 hook 处理
6. **hooks 无控制终端**：不能写 `/dev/tty`，用 `terminalSequence` 替代（v2.1.141+）
7. **`disableAllHooks`**：临时禁用所有 hooks，但**不能**禁用托管策略 hooks

---

## 十一、调试

| 方法 | 用途 |
|---|---|
| `/hooks` 菜单 | 只读查看所有已配置 hooks（类型、来源、详情） |
| `claude --debug-file <path>` | 日志写入指定文件 |
| `claude --debug` | 日志写入 `~/.claude/debug/<session-id>.txt` |
| `CLAUDE_CODE_DEBUG_LOG_LEVEL=verbose` | 匹配器计数、查询匹配等细粒度日志 |

调试日志格式：
```
[DEBUG] Executing hooks for PostToolUse:Write
[DEBUG] Found 1 hook commands to execute
[DEBUG] Executing hook command: <cmd> with timeout 600000ms
[DEBUG] Hook command completed with status 0: <stdout>
```

---

## 十二、Skill/Agent 中声明 Hooks

YAML frontmatter 格式，范围限于组件生命周期：

```yaml
---
name: secure-operations
description: Perform operations with security checks
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/security-check.sh"
---
```

- 支持 `once: true`（仅 skill frontmatter 中有效，每会话只运行一次后移除）
- Subagent 的 `Stop` hooks 自动转为 `SubagentStop`
- 组件不活跃时 hooks 自动清理

---

## 十三、配置快速参考

```json
{
  "hooks": {
    "EventName": [
      {
        "matcher": "ToolName|Pattern",
        "hooks": [
          {
            "type": "command|http|mcp_tool|prompt|agent",
            "command": "script-path",          // command 类型必填
            "url": "http://...",                // http 类型必填
            "server": "mcp-server",             // mcp_tool 类型必填
            "tool": "tool-name",                // mcp_tool 类型必填
            "input": {},                         // mcp_tool 可选
            "prompt": "text with $ARGUMENTS",   // prompt/agent 必填
            "model": "haiku|sonnet",             // prompt/agent 可选
            "if": "Bash(git *)",                 // 通用可选，仅工具事件
            "args": [],                           // command 可选（exec 形式）
            "async": false,                       // command 可选
            "asyncRewake": false,                 // command 可选
            "shell": "bash|powershell",           // command 可选
            "timeout": 600,                       // 通用可选（秒）
            "statusMessage": "Checking...",       // 通用可选
            "once": false,                        // 仅 skill frontmatter
            "headers": {},                         // http 可选
            "allowedEnvVars": []                   // http 可选
          }
        ]
      }
    ]
  }
}
```

---

## 十四、常见陷阱

| 陷阱 | 原因 | 修复 |
|---|---|---|
| exit 1 没阻止操作 | exit 1 = 非阻止错误 | 用 exit 2 阻止 |
| JSON + exit 2 | exit 2 时 JSON 被忽略 | 选一种方式：纯 exit 2 或 exit 0 + JSON |
| shell profile 文本干扰 JSON | `.bashrc` 输出混入 stdout | 确保 hook 脚本 stdout 只输出 JSON |
| UserPromptSubmit hook 卡死 | 默认超时 30s 可能不够 | 设置 `timeout` 字段 |
| Stop hook 无限循环 | 每次阻止 → Claude 继续 → 再次 Stop | 检查 `stop_hook_active` |
| async hook 试图阻止 | 异步 hook 返回时操作已完成 | 拦截用 PreToolUse 同步 hook |
| Windows exec 形式 `.cmd` 失败 | `.cmd` 不是真实可执行文件 | 用 `node` + 脚本路径 |
| MCP SessionStart hook 报错 | MCP 服务器连接可能未完成 | 预期首次运行"未连接"错误 |