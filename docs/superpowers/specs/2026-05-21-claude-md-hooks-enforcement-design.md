# CLAUDE.md 硬性规则 Hooks 强制执行 — 设计文档

**Date**: 2026-05-21
**Status**: Design (pending implementation)
**Scope**: 通过 Claude Code hooks 机制强制执行 CLAUDE.md 中的硬性规则与 COMMON.md 中的目录隔离规则

---

## 1. 背景与目标

### 当前问题

CLAUDE.md 中声明的"硬性"规则（身份确认禁止任何操作、Boot Procedure 必须验证 RoleManager、压缩后必须重载 COMMON/L0）目前完全依赖 AI 自觉遵守。实际表现：

- 身份未确认时 AI 可能仍执行 Read/Grep
- 压缩后 CLAUDE.md 自身被裁剪，AI 不知道需要重载
- COMMON.md "跨角色访问必须走 Subagent" 没有任何技术约束
- Boot Procedure 第 0 步靠 AI 主动执行，可能被跳过

### 目标

用 Claude Code hooks 机制将上述规则转为**技术强制**：
- 身份未确认时硬拦截工具调用
- SessionStart 自动验证 + 启动 RoleManager
- 压缩后自动注入 COMMON.md + L0_Index.md 到上下文
- 跨角色目录访问硬拦截（Subagent 调用例外）

### 非目标

- 不实施 BDD/TDD 流程强制（流程性规则，不适合硬拦截）
- 不实施编码规范（GBK/UTF-8）检查（编码检测复杂度高，留作后续）
- 不实施任务命名规范（暂无明确规则）

---

## 2. 总体架构

### 文件结构

```
.claude/
  settings.json          # hooks 配置（项目级，提交 git，团队共享）
  settings.local.json    # 现有 PowerShell SessionStart hook（迁移后移除）
  hooks/
    check-identity.sh    # UserPromptSubmit + PreToolUse 身份门控
    boot-rolemanager.sh  # SessionStart RoleManager 健康检查 + 上下文注入
    post-compact-reload.sh # PostCompact 重载 COMMON/L0 上下文
    gate-directory.sh    # PreToolUse 目录隔离硬拦截
    warn-directory.sh    # PostToolUse 目录隔离软提醒（Bash 兜底）
```

### 5 个独立脚本，1 组 settings.json 配置

每个流程职责单一，可独立调试/修改。脚本统一从 stdin 读 JSON，统一通过 jq 输出决定，统一访问 RoleManager API。

### Shell 选择

Git Bash（Windows）。所有脚本使用 `#!/bin/bash`，跨平台命令（curl、jq、grep）。

### 配置作用域

项目级 `.claude/settings.json`，提交 git，团队成员共享。现有 `settings.local.json` 中的 SessionStart PowerShell hook 迁移到 `boot-rolemanager.sh` 后从本地配置移除。

---

## 3. 组件设计

### 3.1 check-identity.sh — 身份确认门控

**触发事件**: `UserPromptSubmit` + `PreToolUse`

**职责**: 检查 RoleManager 中当前角色是否已确认；未确认则阻止操作。

**输入**: stdin JSON（hook 输入）
**输出**: stdout JSON（决定） / stderr（错误）

**逻辑**:
1. 从 stdin 读取 hook 输入
2. 提取 `hook_event_name`
3. curl `http://127.0.0.1:5080/api/a2a/identity/current` 查询当前角色
4. 若角色已确认 → exit 0（放行）
5. 若未确认 → 根据事件返回不同 JSON：
   - `UserPromptSubmit`: `{decision: "block", reason: "..."}`
   - `PreToolUse`: `{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: "..."}}`

**容错**:
- RoleManager 不可达 → exit 0（放行）+ stderr 警告。**安全悬挂原则**：避免 RoleManager 故障锁死会话。
- jq 解析失败 → exit 0 + stderr 记录

**配置**:
```json
{
  "UserPromptSubmit": [{
    "hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/check-identity.sh", "timeout": 10}]
  }],
  "PreToolUse": [{
    "matcher": "Read|Grep|Glob|Agent|Edit|Write|Bash",
    "hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/check-identity.sh", "timeout": 10}]
  }]
}
```

**依赖**: RoleManager 提供 `GET /api/a2a/identity/current` → `{"role": "CP-DEV-xzmp"}` 或 `{"role": null}`。**注意**: 此端点需要在 RoleManager 中实现或确认已存在。

### 3.2 boot-rolemanager.sh — Boot Procedure

**触发事件**: `SessionStart`（matcher: `startup` / `resume` / `compact`）

**职责**: 验证 RoleManager 可用性；若未运行尝试启动；注入开发上下文。

**输入**: stdin JSON（含 `source` 字段）
**输出**: stdout JSON（`hookSpecificOutput.additionalContext`）

**逻辑**:
1. 从 stdin 读取 `source` 字段
2. curl `http://127.0.0.1:5080/api/a2a/health` 检查
3. 若不可达 → 启动 RoleManager.exe（cd 到目录后 `./RoleManager.exe &`）→ sleep 2 → 再次 curl
4. 仍不可达 → 输出 `systemMessage` 提示用户手动处理 → exit 0
5. 可达且为 startup/resume → 注入 `additionalContext`：当前 git branch + 提醒按 Boot Procedure 加载 COMMON/L0

**配置**:
```json
{
  "SessionStart": [
    {"matcher": "startup", "hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/boot-rolemanager.sh", "timeout": 15}]},
    {"matcher": "resume", "hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/boot-rolemanager.sh", "timeout": 15}]},
    {"matcher": "compact", "hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/boot-rolemanager.sh", "timeout": 15}]}
  ]
}
```

**迁移**: 替代现有 `settings.local.json` 中的 PowerShell SessionStart hook。

### 3.3 post-compact-reload.sh — 压缩后重载

**触发事件**: `PostCompact`（无 matcher，manual + auto 都触发）

**职责**: 压缩后查询当前角色 → 拼接 COMMON.md + 角色 L0_Index.md → 通过 `additionalContext` 注入。

**输入**: stdin JSON
**输出**: stdout JSON（`hookSpecificOutput.additionalContext`）

**逻辑**:
1. 从 stdin 读 hook 输入
2. curl 查询当前角色
3. 若无角色 → 注入提醒"压缩完毕，重读 COMMON 并确认角色"
4. 若有角色 → 读取 `${CLAUDE_PROJECT_DIR}/COMMON.md` + `${CLAUDE_PROJECT_DIR}/<role>/L0_Index.md`
5. 拼接为 additionalContext 注入

**关键**: Claude Code 自动处理 >10000 字符的 additionalContext（落盘 + 预览）。无需手动截断。

**配置**:
```json
{
  "PostCompact": [{
    "hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/post-compact-reload.sh", "timeout": 10}]
  }]
}
```

**为什么 PostCompact 而非 PreCompact**: PreCompact 在压缩前触发，压缩本身会清理上下文；PostCompact 在压缩后注入，新上下文保留 hook 输出。

### 3.4 gate-directory.sh — 目录隔离硬拦截

**触发事件**: `PreToolUse`（matcher: `Read|Edit|Write|Glob|Grep`）

**职责**: 拦截当前角色访问其他角色目录的工具调用；Subagent 调用例外（COMMON.md 第 3 条允许）。

**输入**: stdin JSON（含 `tool_name`、`tool_input`、可选 `agent_id`）
**输出**: stdout JSON（permissionDecision: deny / 放行）

**逻辑**:
1. 从 stdin 读 hook 输入
2. 检查 `agent_id` 字段：存在 → 放行（Subagent 调用允许跨角色）
3. curl 查询当前角色
4. 若无角色 → 放行（由 check-identity.sh 处理）
5. 从 `tool_input` 提取路径：`file_path` / `path` / `pattern`
6. 遍历已知角色目录列表，检查路径是否包含其他角色目录名
7. 命中 → 返回 `permissionDecision: "deny"` + 提示用 Subagent

**角色目录列表**（与 COMMON.md 一致）:
- `CP-DEV-xzmp`
- `CPP-GameSVR-DEV-xzmp`
- `Creator-Client-DEV-xzmp`
- `LUA-Client-DEV-xzmp`
- `ChangData-Seeker` / `ChangData-Seeker-125`
- `Service-Svr-Dev`

**配置**:
```json
{
  "PreToolUse": [{
    "matcher": "Read|Edit|Write|Glob|Grep",
    "hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/gate-directory.sh", "timeout": 5}]
  }]
}
```

### 3.5 warn-directory.sh — Bash 兜底软提醒

**触发事件**: `PostToolUse`（matcher: `Bash`）

**职责**: Bash 命令字符串可能包含跨角色路径但 PreToolUse 难精确解析。事后字符串匹配提醒 AI 下次用 Subagent。

**输入**: stdin JSON（含 `tool_input.command`）
**输出**: stdout JSON（`hookSpecificOutput.additionalContext`）

**逻辑**:
1. 从 stdin 读 hook 输入
2. curl 查询当前角色
3. 若无角色 → 放行
4. 从 `tool_input.command` 字符串中搜索其他角色目录名
5. 命中 → 注入 `additionalContext` 提醒"下次跨角色用 Subagent"

**配置**:
```json
{
  "PostToolUse": [{
    "matcher": "Bash",
    "hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/warn-directory.sh", "timeout": 5}]
  }]
}
```

---

## 4. 数据流

### 身份确认场景（用户提交提示）

```
用户提交提示
  ↓
UserPromptSubmit hook 触发
  ↓
check-identity.sh
  ↓
curl http://127.0.0.1:5080/api/a2a/identity/current
  ↓
  ├─ role 存在 → exit 0 → 提示进入 Claude 处理
  └─ role null  → {decision: "block", reason: "..."} → 提示被拒绝，用户看到原因
```

### 工具调用场景

```
Claude 决定调用 Read("path/to/file")
  ↓
PreToolUse hook 链触发（两个 hook 并发）
  ├─ check-identity.sh    → 检查身份
  └─ gate-directory.sh    → 检查目录
  ↓
两者都需 allow 才执行；任一 deny 即拒绝
优先级: deny > defer > ask > allow
```

### 压缩场景

```
上下文压缩完成
  ↓
PostCompact hook 触发
  ↓
post-compact-reload.sh
  ↓
curl 查询角色 → 读 COMMON.md + L0_Index.md
  ↓
注入 additionalContext → Claude 下个轮次自动看到
```

### SessionStart 场景

```
新会话/恢复/压缩后
  ↓
SessionStart hook（matcher: startup/resume/compact）触发
  ↓
boot-rolemanager.sh
  ↓
健康检查 → [失败则启动] → 再检查
  ↓
注入 additionalContext（branch + Boot Procedure 提醒）
```

---

## 5. 错误处理策略

### 安全悬挂原则

身份门控、目录隔离的 hook **宁可放行也不锁死会话**。RoleManager 故障是运行时事件，hooks 不应让用户完全无法操作。

| 场景 | 处理 |
|---|---|
| curl 连接失败 | exit 0（放行）+ stderr 警告 |
| API 返回非 JSON | jq `// empty`，按未确认处理 |
| jq 命令本身缺失 | exit 0 + stderr 错误日志 |
| 脚本 bash 语法错误 | hook 进程非 0 退出 → 非阻止错误，工具继续 |
| 脚本超时 | hook 超时 → 非阻止错误 |

### 故意阻塞场景

唯一允许阻塞的情况：**RoleManager 可达且明确返回未确认角色**。这是产品逻辑要求的阻塞。

### Boot 阻塞例外

`boot-rolemanager.sh` 中即使 RoleManager 启动失败也 exit 0（仅 systemMessage 提示）。SessionStart hook 阻塞会导致会话无法启动。

---

## 6. 性能与优化

### 单次 hook 开销估算

| Hook | 频率 | 单次成本 |
|---|---|---|
| check-identity.sh | 每提示 + 每工具调用 | ~5ms（localhost curl） |
| boot-rolemanager.sh | 每会话启动 | ~2s（含可能的进程启动） |
| post-compact-reload.sh | 每次压缩 | ~50ms（curl + 2 个文件读） |
| gate-directory.sh | 每 Read/Edit/Write/Glob/Grep | ~5ms |
| warn-directory.sh | 每 Bash | ~5ms |

### 优化方向（暂不实施）

- **SessionStart 写入 CLAUDE_ENV_FILE**: 将当前角色写为环境变量，后续 hook 读 env 而非 curl。问题：用户切换角色后环境变量不更新。
- **响应缓存**: 在 tmp 文件缓存角色查询结果 + TTL。增加复杂度。

**决策**: 先按当前方案实施，实测开销明显后再优化。

---

## 7. 安全考虑

- **shell 变量必须引用**: 所有 `$VAR` 改为 `"$VAR"`，避免空格/特殊字符注入
- **路径绝对化**: 使用 `${CLAUDE_PROJECT_DIR}` 引用项目路径
- **API 输入校验**: jq 解析后必须用 `// empty` 处理缺失字段
- **不信任 stdin**: hook 输入可能含恶意构造，但 hook 仅用于决定，不执行 stdin 字符串
- **敏感文件跳过**: gate-directory.sh 不应基于 `.env`、`.git/` 路径做策略（不属于角色目录）

---

## 8. 测试策略

### 手动测试用例

1. **身份未确认 + 用户提示** → 提示被拒绝
2. **身份未确认 + 工具调用** → 工具被 deny
3. **身份已确认 + 同角色目录访问** → 放行
4. **身份已确认 + 跨角色目录访问** → deny + 提示用 Subagent
5. **Subagent 内跨角色访问** → 放行（agent_id 存在）
6. **RoleManager 未启动 → 启动新会话** → SessionStart 自动启动 RoleManager
7. **RoleManager 完全不可用** → check-identity.sh 放行 + stderr 警告
8. **手动 /compact** → PostCompact 注入 COMMON + L0
9. **Bash 命令访问其他角色目录** → 不阻止但 PostToolUse 提醒

### 测试方法

每个脚本独立可测试 — 准备 stdin JSON fixture，运行脚本，断言 stdout/exit code：

```bash
echo '{"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "CPP-GameSVR-DEV-xzmp/foo.cpp"}}' | \
  ./.claude/hooks/gate-directory.sh
# 期望: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}
```

---

## 9. 依赖项

| 依赖 | 版本 | 用途 |
|---|---|---|
| Git Bash | Windows 默认 | shell 执行环境 |
| curl | Git Bash 自带 | HTTP API 调用 |
| jq | 需确认/安装 | JSON 解析 |
| RoleManager | 现有项目 | 身份/健康 API |
| **新增** RoleManager API: `GET /api/a2a/identity/current` | 需实现 | 查询当前角色 |

**前置条件**:
- jq 必须可用（验证: `jq --version`）
- RoleManager 必须暴露 `GET /api/a2a/identity/current` 端点，返回 `{"role": "<role-name>"}` 或 `{"role": null}`

---

## 10. 实施清单

1. 验证 jq 可用，验证 RoleManager `identity/current` 端点（不存在则先实现）
2. 创建 `.claude/hooks/` 目录
3. 编写 5 个 hook 脚本，使用 `chmod +x` 设置可执行
4. 更新 `.claude/settings.json` 注册所有 hooks
5. 从 `.claude/settings.local.json` 移除现有 PowerShell SessionStart hook
6. 手动执行测试用例 1-9
7. 提交 `.claude/settings.json` + `.claude/hooks/` 到 git
8. `.claude/settings.local.json` 保持本地

---

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| RoleManager API 端点不存在 | 实施前先在 RoleManager 中确认/实现 |
| jq 在某些 Git Bash 中未安装 | 文档说明依赖；hook 检测缺失时 exit 0 + 警告 |
| 路径匹配误判（如文件名碰巧含角色目录名） | 用更严格的边界匹配（`grep -E "/<role>/"`） |
| Hook 性能拖慢 Claude | 实测后按需加缓存 |
| 用户切换角色后未通知 RoleManager | 用户责任；hook 仅信任 API 当前状态 |
| 现有 PowerShell hook 用户依赖 | 迁移前充分测试 bash 版本 |

---

## 12. 后续可扩展

本次不实施但可基于此架构添加：

- **编码规范检查**（PreToolUse on Edit/Write）：GBK/UTF-8 校验
- **任务命名规范**（TaskCreated）：强制任务标题格式
- **Notes API 写后自动 git 提交**（PostToolUse on mcp__a2a__*）
- **Stop hook 完成度检查**（确认任务真正完成才允许停止）
