# service-server (Rust 重写)

serviceServer 的 Rust 重写, 迁入 infoServer/serviceGroup/serviceServer/。SDD 任务: `service-svr Rust重构精简` (skillrepo `SDD/ready/service-svr Rust重构精简/`)。

## 构建 / 测试

```bash
cargo build          # 编译
cargo test           # 全测试 (rstest 参数化 + #[test])
cargo run            # 跑 :5000 (需 config.json, 默认 cwd, 或 SERVICESVR_CONFIG 环境变量)
```

## 部署 (整包 + 静态资源直推, 2026-09-21 起为主路)

```bash
./deploy.bat                        # 本机 (:5099 发布引导)
./deploy.bat 192.168.102.53:5099    # 堡垒机 53 (可加 --token <TOK>)
```

- **链路**: `build.bat` (cargo build --release) → `make_deploy_pack.py --only serviceServer-rust --push <目标>:5099` → 目标机 **L2 发布面**（`run.py` + `deploy_service.py`，2026-09-22 起；此前在 legacy）解压校验 → 非 exe 就地替换(带备份) → 包内**服务** exe 交**宿主 swap_exe** 停/换/起换代 → 任一步失败回滚。
- **助手 exe（非服务二进制，如 `serviceServer-legacy/assetTool.exe`）**: 走**就地替换**(带备份)，**不经** swap_exe —— 它没有宿主服务/端口可换（原逻辑会把它判 `unmapped_exe` 令发布失败）。三处清单必须同步：`src/routes/assets.rs::HELPER_EXE` / `make_deploy_pack.py::HELPER_EXES`（进不进包）/ **`deploy_service.py::HELPER_EXES`**（就地替换 vs 判失败；该项 2026-09-22 随发布器搬到 L2，legacy 那份已随发布通道摘除）。构建：`serviceServer-legacy/build_assetTool.bat`（PyInstaller onefile；产物**不入库** —— 该目录 `.gitignore` 已忽略 `*.exe`，语义同 `target/release/*.exe`）。
- **为何直连 :5099**: 换代时 :5000 自己就是被停目标, 走前端轮询在停机窗口必断。**2026-09-22 起该面由 L2 (`run.py`) 托管**，legacy 退居 **:5098** 只服务 CP 路由（`/api/deploy/*` 在 legacy 上已 404）；Rust 反代目标 = `SERVICESVR_LEGACY_URL`，自身重启委派 = `SERVICESVR_DEPLOY_URL`。
- **包动了哪一层决定收尾**（2026-09-22 起）: `run.py`/`start.py` → 发布器自更新（停 L3 → 非保留码退出 → L1 `--supervise` 重拉）；`main.py`/`service_manager.py` → reseat L3（L2 不死）；`serviceServer-legacy/**` → 请宿主 restart legacy(5098)。
- **为何必须 venv 的 python**: 系统 python 无 PyYAML → 打包第一步就报错 (2026-09-21 实测); `deploy.bat` 已写死 `.venv\Scripts\python.exe`。
- **exe 打包源 = cargo 产物**: 运行位 exe 被运行中进程锁着, 本机 `copy /Y` 落位必然失败; `make_deploy_pack.py` 在 `target/release/<basename>` 比运行位新时自动改用它打包 (manifest `exe_src` 留痕), 换代由目标机宿主完成。
- **进度/结果**: 目标机 `GET /api/deploy/log` — record 看 `exe_done` / `failures` / `host_probe`。
- 服务自身经 `/api/services/status` 的 `service-server_self` 条目自陈列, 页面提供「重启自身 + 配置编辑」(重启经宿主, 不做自杀式换代)。

### 旧路 (svn 分发, 保留备用)

```bash
./build.bat        # 需先停服, 否则 copy 撞运行位占用
./push.bat         # svn commit 两目录 → 远端 ctl_client.py --socket svc update
```

- svn 仓库: `https://192.168.102.112/svn/common/trunk/自有平台业务/斗雀工作室/scriptTools/infoServer` (serviceGroup 是其子目录)。
- **不再作主路**: svn 工作副本有状态 (work queue / 锁 / incomplete), 且版本控制在管运行位 exe → 换代必撞占用 (2026-09-21 事故根因)。

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
- ✅ PathMap + path_check + encoding + backup + atomic_write
- ✅ T1 全 (path 半 + Win32 status 半: windows crate SCM + status_cache TTL)
- ✅ T2 配置编辑簇 (原子写 + 滚动备份 max3 + 编码探测 + content/save/branches 全套)
- ✅ Strangler 反代 (proxy.rs fallback → legacy Flask) + Phase 1/2 上线 (Rust:5000 + legacy:5099 live)
- ✅ /api/config GET + /api/fetch-title Rust 化 (reqwest 迁移模式)
- ✅ fileontimer 移除 + 死路径 blocklist (RAG/A2A/AI/fileontimer 前台 404)
- 🟡 services 控制簇: start/stop/restart/delete Rust 化 (SCM ControlService + StartService + DeleteService), deploy/start-all/update 留 legacy
- ✅ templates 簇 Rust 化 (rusqlite bundled, 复用 legacy templates.db, 3 路由 save/get/delete)
- ✅ status shape 全对齐: display_name + exe_path + ports 真值 (PID toolhelp32 + IP Helper, 28 服务 ports 全 match legacy)
- ✅ [2026-09-21] 卡片时间字段: `exe_mtime` (exe 文件 mtime) + `updated_at` (服务目录内产物最晚 mtime, 非递归, 白名单 exe/pdb/dll/ini/json/lua/html/js/css/png) —— 均 Unix 秒, 前端 `fmtTs` 本地化; 未部署或无产物则 null (卡片显「—」)
- ✅ [2026-08-04] 文件访问簇放开 + download 新增: `list_files`/`get_content` 不限扩展名 (任意文件读/列, 含 exe/dll/dmp/log); 新增 `GET /api/config/file/download` (二进制兜底, 上限 200MB, RFC 5987 pct-encode 中文文件名); `save_file` 保持 ini/json/lua 白名单; error 加 `TooLarge(u64)`
- ⬜ 货币调控留 legacy (DB 依赖)
- ⬜ T4 PyO3 (待触发) + legacy 死功能清理
- cargo test 94 通过, release exe 6.0MB

## 旧版参考源

`D:\Codlib\VscodeCodlib\Python\infoServer\serviceGroup\serviceServer-legacy\` (旧 Flask, 被 Rust 反代, 删除清单内的死功能不迁):
- `CustomRoute/ServiceRoute.py` — 路由逻辑与契约源头
- `Service.py` — `get_all_service_status` / `read_file_content` / `save_file_content` (逻辑参照, 实现重写规避旧 bug)
- `JsonConfigParser.py` — config.json schema
- 死功能 (不迁): `CommonTools/ragKnowledge/`, `CommonTools/agent/`, `src/A2AFile/`, `src/CTWL-GAMESVR-SKILL/`, AI 路由 (/ai-manager, /api/benchmark/*, /api/claude/*, /api/ai-proxy/*, /rag-qa, /api/rag/*)
- 例外: `/api/makedeal/*` (做牌接口) 曾列入死功能, 2026-09-13 从 `proxy.rs` DEAD_PREFIXES 摘除放行 — 该接口仍在用, 实现在 legacy `CustomRoute/ServiceRoute.py` 末尾 (源: svn scriptTools/serviceServer caiyf r58900/r59114/r59912)
