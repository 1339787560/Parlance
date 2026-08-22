# statistic-server BUILD 清单

DeepSeek 代理统计服务的 Rust 构建与部署步骤（build 清单）。

## 依赖

- Rust 工具链（cargo + rustc，需支持 edition 2024）
- 无需 .venv（单二进制，bundled SQLite）

## 构建

```bash
cd serviceGroup/statisticServer
cargo build --release
```

产物：`serviceGroup/statisticServer/target/release/statistic-server`（mac/linux）/ `statistic-server.exe`（win）。

## 运行

```bash
DEEPSEEK_API_KEY=sk-... ./target/release/statistic-server --port 5002
```

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | 上游 API Key（客户端未提供时用） |
| `ANTHROPIC_TARGET` | `https://api.deepseek.com/anthropic` | Anthropic 格式目标 |
| `OPENAI_TARGET` | `https://api.deepseek.com/v1` | OpenAI 格式目标 |
| `PORT` | `5002` | 监听端口 |
| `DB_PATH` | `stats.db` | SQLite 路径 |

## 部署到 infoServer 服务组

1. `cargo build --release`
2. 更新 `config.yaml` 中 statistic-server 的 command 指向产物：
   - mac：`./serviceGroup/statisticServer/target/release/statistic-server`
   - win：`...\statistic-server.exe`
3. 重启子服务：`cwd_infoserver_restart(port=5002)`（或热更 exe：`cwd_infoserver_swap_exe(5002)`）
4. 探活：`curl http://127.0.0.1:5002/health`

## 测试

```bash
cargo test
```

## ignore

`target/` 构建产物已由仓库 `.gitignore`（`*/target`、`**/target`）忽略；`stats.db` 由 `*.db` 忽略。
