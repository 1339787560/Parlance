# service-server (Rust 重写)

serviceServer 的 Rust 重写, 迁入 infoServer/serviceGroup/serviceServer/。SDD 任务: `service-svr Rust重构精简` (skillrepo `SDD/ready/service-svr Rust重构精简/`)。

## 构建 / 测试

```bash
cargo build          # 编译
cargo test           # 全测试 (rstest 参数化 + #[test])
cargo run            # 跑 :5000 (需 config.json, 默认 cwd, 或 SERVICESVR_CONFIG 环境变量)
```

## 测试约定 (pytest 风格, 质量硬门槛)

- **参数化优先**: 用 `rstest` 的 `#[rstest]` + `#[case::name]` 表达边界矩阵 (类 pytest `parametrize`)。一组 case = 一份 QA 文档。
- **命名**: `test_<模块>_<场景>_<期望>`, 自描述, 不依赖断言文案。
- **AAA 结构**: 非平凡用例加 `// Arrange / // Act / // Assert` 注释。
- **无魔数**: 路径/服务名等用命名常量或 fixture。
- **位置**: 单元测试 inline (`#[cfg(test)] mod tests`); 跨模块集成测试进 `tests/` 目录。
- **fixture**: `tempfile::tempdir` 做临时 config.json (pytest `tmp_path` 等价); 复杂共享前缀抽 helper 函数。

范例: `src/path_check.rs` 的 `test_is_within_boundary_matrix`, `src/path_map.rs` 的 `test_path_map_abspath_normalized`。

## 架构指针

- **path 与 status 拆分** (配置编辑器卡顿根治):
  - `path_map::PathMap` — service_id→path 静态映射, mtime 失效缓存, 零 Win32 syscall。配置编辑簇路径校验专用。
  - `status_cache` (T1 待建) — 动态 status, TTL 缓存, 走 Win32。仅 `/api/services/status` 等状态端点用。
- **路径越权校验**: `path_check::is_within` 分量级比较, 修旧 `startswith` prefix bug。所有文件操作 handler 必须经它。
- **分层**: route handler (axum, src/routes/) → 业务逻辑 → data (config.json/FS/DB)。Win32 与 DB 抽 trait 便于 mock。
- **错误**: 集中 `error::AppError` + `IntoResponse`, 产与旧 Flask 兼容的 `{success, message}` JSON。
- **状态注入**: `state::AppState` (Arc<PathMap>) 通过 axum `State` 注入。

## 当前进度 (T1 path 半已成)

- ✅ Cargo.toml + axum 骨架 (:5000)
- ✅ PathMap + path_check (cargo test 15 通过)
- ✅ /api/config/files 轻量端点
- ✅ T1 全 (path 半 + Win32 status 半: windows crate SCM + status_cache TTL)
- ✅ T2 配置编辑簇 (原子写 + 滚动备份 max3 + 编码探测 + content/save 路由)
- ✅ T3 config 分支路由 (branches/create/switch/remove + checks)
- ✅ Strangler 反代 (proxy.rs fallback → legacy Flask) + Phase 1 上线验证 (Rust:5000 + legacy:5099)
- ✅ Phase 2 物理整合 (Flask 搬 infoServer/serviceGroup/serviceServer-legacy/)
- ⬜ T3 其余簇 (货币调控/文件浏览/SVN/模板/抓取, ~30 路由, legacy 渐进迁)
- ⬜ T4 PyO3 兜底 (待具体不支持 API 触发) + 删除清理
- cargo test 53 通过, release exe 3.7MB

## 旧版参考源

`D:\Codlib\VscodeCodlib\Python\infoServer\serviceGroup\serviceServer-legacy\` (旧 Flask, 被 Rust 反代, 删除清单内的死功能不迁):
- `CustomRoute/ServiceRoute.py` — 路由逻辑与契约源头
- `Service.py` — `get_all_service_status` / `read_file_content` / `save_file_content` (逻辑参照, 实现重写规避旧 bug)
- `JsonConfigParser.py` — config.json schema
- 死功能 (不迁): `CommonTools/ragKnowledge/`, `CommonTools/agent/`, `src/A2AFile/`, `src/CTWL-GAMESVR-SKILL/`, AI 路由 (/ai-manager, /api/benchmark/*, /api/claude/*, /api/ai-proxy/*, /api/makedeal/*, /rag-qa, /api/rag/*)
