# DeepSeek 代理统计服务

透明代理：`http://127.0.0.1` → `https://api.deepseek.com/anthropic`，自动转换 Claude 模型名为 DeepSeek 模型名，记录 Token 用量、缓存命中率及费用。

---

## 快速开始

```bash
set DEEPSEEK_API_KEY=sk-your-key
python proxy_server.py --port 5002
```

Claude Code 使用：

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:5002 claude
```

## 功能

### 透明代理
- 自动映射 Claude 模型 → DeepSeek V4 模型（`claude-sonnet/haiku` → `deepseek-v4-flash`，`claude-opus` → `deepseek-v4-pro`）
- 旧别名 `deepseek-chat` / `deepseek-reasoner` 已随 V4 退役（2026-07-24），且均为 **Flash 档**（reasoner = Flash 思考档，非 Pro），自动重写为 `deepseek-v4-flash`
- 支持流式（SSE）和非流式请求
- 透传 `x-claude-code-session-id` 头标识会话

### 费用计算（DeepSeek V4 峰谷计价，元 / 百万 tokens）

| 模型 | 计费项 | 平时 | 高峰(北京时间 9:00-12:00 / 14:00-18:00) |
|------|--------|------|------|
| Flash (`deepseek-v4-flash`) | 输入未命中 / 输入命中 / 输出 | ¥1 / ¥0.02 / ¥2 | ¥2 / ¥0.04 / ¥4 |
| Pro (`deepseek-v4-pro`) | 输入未命中 / 输入命中 / 输出 | ¥3 / ¥0.025 / ¥6 | ¥6 / ¥0.05 / ¥12 |

费用 = `(输入未命中 × 未命中单价 + 缓存命中 × 命中单价 + 输出 × 输出单价) / 1_000_000`，高峰时段整体 ×2。

> 缓存命中段不重复计费：`输入未命中` = `prompt_tokens - cache_hit_tokens`。
> 每次请求按请求时刻落库 `cost`，聚合统计直接 `SUM(cost)`，保证峰谷计价精确（旧数据启动时自动迁移补算）。

### 统计看板

打开 `http://127.0.0.1:5002` 查看 5 个标签页：

| 标签 | 内容 |
|------|------|
| **总览** | 累计请求数、Token 用量、缓存命中、总费用、各模型费用明细 |
| **会话** | 按 `session_id` 聚合，点击查看会话内任务明细 |
| **任务** | 自适应切分的任务列表（每次提问到回答的全过程归为一任务） |
| **按日** | 每日汇总的用量和费用 |
| **请求明细** | 最近 100 次请求详情 |

### 实时推送（SSE）

前端使用 **Server-Sent Events** 替代 HTTP 轮询：

- 新请求完成时立刻推送 `new_data` 事件，页面即时刷新
- 30 秒兜底刷新（即使无事件也定期更新）
- SSE 断开时自动降级为 10 秒轮询

### 自适应任务切分

使用 **Median + 2×MAD** 统计算法自动检测请求爆发模式：

- 每次提问 + 思考 + tool call + 回答 = 一个任务
- 自适应你的节奏——打字快则阈值小，思考久则阈值大
- 无需手动配置间隔

可通过 `?mode=fixed&gap=60` 回退到固定间隔模式。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events` | SSE 实时事件流 |
| GET | `/api/stats` | 聚合统计（总用量 + 会话列表） |
| GET | `/api/stats/detail` | 最近 100 条请求明细 |
| GET | `/api/stats/daily` | 每日汇总 |
| GET | `/api/stats/tasks` | 任务列表（支持 `?session=` 筛选、`?mode=adaptive\|fixed`、`?gap=N`） |
| GET | `/health` | 健康检查 |

## 数据存储

SQLite 数据库，默认 `stats.db`，可通过 `DB_PATH` 环境变量或 `--db` 参数修改。

## 项目结构

```
statisticServer/
├── proxy_server.py    # 代理服务器 + 统计 API
├── static/
│   └── index.html     # 统计看板前端
└── stats.db           # SQLite 数据库（自动创建）
```
