# RTK 用户高频命令手册

> 基于源码 `src/main.rs` Commands enum 提炼。含所有子命令、常用参数、典型用法。
> Hook 模式下大部分命令自动重写，用户无需手动加 `rtk` 前缀。

---

## 全局标志

| 标志 | 作用 |
|---|---|
| `-v` / `-vv` / `-vvv` | 递增调试信息（调试消息 → 执行命令 → 原始输出） |
| `--ultra-compact` / `-u` | ASCII 图标 + 内联格式，极致压缩 |
| `--skip-env` | 子进程注入 `SKIP_ENV_VALIDATION=1`（Next.js/tsc/prisma） |

---

## 1. Git / GitHub / GitLab

### rtk git

| 子命令 | 用法 | 输出特征 | 压缩率 |
|---|---|---|---|
| `diff` | `rtk git diff [--stat] [--cached]` | 仅变更行 | 85%+ |
| `log` | `rtk git log [--oneline] [-10]` | 单行提交摘要 | 80%+ |
| `status` | `rtk git status` | 精简文件状态 | 85%+ |
| `show` | `rtk git show <hash>` | 提要 + stat + 压缩 diff | 80%+ |
| `add` | `rtk git add [-A] <files>` | → `ok` | 99%+ |
| `commit` | `rtk git commit -m "msg"` | → `ok <hash>` | 99%+ |
| `push` | `rtk git push [-u origin main]` | → `ok <branch>` | 99%+ |
| `pull` | `rtk git pull [--rebase]` | → `ok <stats>` | 99%+ |
| `branch` | `rtk git branch [-d <name>]` | 精简分支列表 | 70%+ |
| `fetch` | `rtk git fetch` | → `ok fetched (N new refs)` | 99%+ |
| `stash` | `rtk git stash [list\|pop\|drop]` | 精简列表 | 70%+ |
| `worktree` | `rtk git worktree [add\|remove\|list]` | 精简列表 | 70%+ |

**Git 全局选项**（透传给底层 git）：

```
-C <path>          切换目录
-c key=value       配置覆盖
--git-dir <path>   .git 目录路径
--work-tree <path> 工作树路径
--no-pager         禁用分页
--no-optional-locks 跳过可选锁
--bare             裸仓库
--literal-pathspecs 按字面处理路径
```

**其他 git 子命令**自动透传（不识别的子命令原样执行）。

### rtk gh

```
rtk gh pr list                     PR 列表
rtk gh pr view 123                 PR 详情（去 ASCII 艺术）
rtk gh pr merge 123                合并 PR
rtk gh issue list                  Issue 列表
rtk gh run list                    CI 运行列表
rtk gh repo view                   仓库信息
```

### rtk glab

```
rtk glab mr list                   MR 列表
rtk glab issue list                Issue 列表
rtk glab ci trace                  CI 日志
rtk glab pipeline list             管道列表
rtk -R owner/repo glab mr list     指定仓库
rtk -g mygroup glab issue list     指定组
```

### rtk gt (Graphite)

| 子命令 | 用法 |
|---|---|
| `log` | `rtk gt log` 压缩堆栈日志 |
| `submit` | `rtk gt submit` 提交 PR |
| `sync` | `rtk gt sync` 同步 |
| `restack` | `rtk gt restack` 重排 |
| `create` | `rtk gt create` 创建分支 |
| `branch` | `rtk gt branch` 分支信息 |

---

## 2. Rust / Cargo

### rtk cargo

| 子命令 | 用法 | 输出特征 | 压缩率 |
|---|---|---|---|
| `build` | `rtk cargo build [--release]` | 去 "Compiling" 行，仅保留错误 | 80%+ |
| `test` | `rtk cargo test` | 仅显示失败测试 | 94%+ |
| `clippy` | `rtk cargo clippy --all-targets` | 按 lint 规则分组 | 70%+ |
| `check` | `rtk cargo check` | 去 "Checking" 行，仅保留错误 | 80%+ |
| `install` | `rtk cargo install <crate>` | 去依赖编译行 | 80%+ |
| `nextest` | `rtk cargo nextest run` | 仅显示失败测试 | 94%+ |

**通用 runner 快捷方式**：

```
rtk err <command>         仅显示错误/警告
rtk test <command>        仅显示失败测试
```

示例：
```
rtk err cargo build
rtk test cargo test --lib
```

---

## 3. JS/TS 生态

### rtk lint (ESLint)

```
rtk lint                        检查当前项目
rtk lint src/                   指定目录
rtk lint --fix                  自动修复
```

按规则分组违规（如 `no-unused-vars: 23`），压缩率 70%+。

### rtk tsc

```
rtk tsc                         类型检查
rtk tsc --noEmit                仅检查不输出
```

按错误码分组，压缩率 80%+。

### rtk vitest / rtk jest

```
rtk vitest                      运行测试
rtk vitest --run                单次运行
rtk jest                        Jest 测试
```

仅显示失败测试，压缩率 90%+。

### rtk playwright

```
rtk playwright                  E2E 测试
rtk playwright --headed         有头模式
```

仅显示失败用例，压缩率 90%+。

### rtk next

```
rtk next build                  Next.js 构建
rtk next dev                    开发服务器（透传）
```

压缩构建输出，压缩率 70%+。

### rtk prisma

| 子命令 | 用法 | 说明 |
|---|---|---|
| `generate` | `rtk prisma generate` | 去 ASCII 艺术 |
| `migrate dev` | `rtk prisma migrate dev -n init` | 创建迁移 |
| `migrate status` | `rtk prisma migrate status` | 迁移状态 |
| `migrate deploy` | `rtk prisma migrate deploy` | 部署迁移 |
| `db push` | `rtk prisma db push` | 推送 schema |

### rtk pnpm

| 子命令 | 用法 | 输出 |
|---|---|---|
| `list` | `rtk pnpm list [-d 1]` | 超密依赖列表 |
| `outdated` | `rtk pnpm outdated` | `pkg: old → new` |
| `install` | `rtk pnpm install` | 过滤进度条 |
| `typecheck` | `rtk pnpm typecheck` | 委托给 tsc 过滤 |

**Monorepo 过滤**：
```
rtk pnpm --filter @app1 --filter @app2 list
```

### rtk npm / rtk npx

```
rtk npm run build               npm 脚本（去样板输出）
rtk npx eslint src/             智能路由到 rtk lint
rtk npx tsc --noEmit            智能路由到 rtk tsc
rtk npx prisma generate         智能路由到 rtk prisma
```

### rtk prettier / rtk format

```
rtk prettier --check .          格式检查
rtk prettier --write .          格式化
rtk format                      通用格式检查（自动检测 prettier/black/ruff format）
```

---

## 4. Python 生态

### rtk ruff

```
rtk ruff check                  Lint（JSON API 分组）
rtk ruff check --fix            自动修复
rtk ruff format --check         格式检查
rtk ruff format                 格式化
```

按规则分组，压缩率 80%+。

### rtk pytest

```
rtk pytest                      运行测试
rtk pytest tests/test_auth.py   指定文件
rtk pytest -k "test_login"      关键字过滤
```

状态机解析，仅显示失败，压缩率 90%+。

### rtk mypy

```
rtk mypy src/                   类型检查
```

按错误码分组，压缩率 70%+。

### rtk pip

```
rtk pip list                    精简包列表
rtk pip outdated                过期包
rtk pip show requests           包详情
```

自动检测 `uv`（若存在则用 `uv pip`），压缩率 70%+。

---

## 5. Go 生态

### rtk go

| 子命令 | 用法 | 压缩率 |
|---|---|---|
| `test` | `rtk go test ./...` | NDJSON 流解析，90%+ |
| `build` | `rtk go build ./...` | 仅错误，80%+ |
| `vet` | `rtk go vet ./...` | 精简输出，75%+ |

### rtk golangci-lint

```
rtk golangci-lint run           运行全部 linter
rtk golangci-lint run --timeout 5m
```

JSON 解析按规则分组，压缩率 85%。

---

## 6. Ruby 生态

### rtk rake

```
rtk rake test                   Minitest（Rails）
rtk rake test TEST=path/test.rb 指定文件
```

状态机解析，压缩率 85%+。

### rtk rspec

```
rtk rspec                       运行测试
rtk rspec spec/models/          指定目录
rtk rspec --tag focus           标签过滤
```

注入 `--format json`，去 Spring/SimpleCov 噪声，压缩率 60%+。

### rtk rubocop

```
rtk rubocop                     Lint
rtk rubocop -a                  自动修复
rtk rubocop -A                  安全+不安全修复
```

注入 `--format json` 按规则分组（autocorrect 模式不注入），压缩率 60%+。

---

## 7. .NET 生态

### rtk dotnet

| 子命令 | 用法 |
|---|---|
| `build` | `rtk dotnet build` |
| `test` | `rtk dotnet test` |
| `restore` | `rtk dotnet restore` |
| `format` | `rtk dotnet format` |

不支持子命令自动透传。

---

## 8. JVM / Android

### rtk gradlew

```
rtk gradlew assembleDebug               构建
rtk gradlew testDebugUnitTest           单元测试
rtk gradlew lint                        Lint
rtk gradlew connectedDebugAndroidTest   集成测试
```

压缩率 70%+。

---

## 9. 云 / 基础设施

### rtk aws

```
rtk aws sts get-caller-identity          身份信息
rtk aws s3 ls                            S3 列表
rtk aws ec2 describe-instances           EC2 实例
rtk aws ecs list-clusters                ECS 集群
```

强制 JSON 输出 + 压缩，压缩率 60%+。

### rtk docker

| 子命令 | 用法 |
|---|---|
| `ps` | `rtk docker ps` 精简容器列表 |
| `images` | `rtk docker images` 精简镜像列表 |
| `logs` | `rtk docker logs <container>` 去重日志 |
| `compose ps` | `rtk docker compose ps` 服务列表 |
| `compose logs` | `rtk docker compose logs [service]` 去重日志 |
| `compose build` | `rtk docker compose build [service]` 构建摘要 |

### rtk kubectl

| 子命令 | 用法 |
|---|---|
| `pods` | `rtk kubectl pods [-n ns] [-A]` 精简 Pod 列表 |
| `services` | `rtk kubectl services [-n ns] [-A]` 精简 Service 列表 |
| `logs` | `rtk kubectl logs <pod> [-c container]` 去重日志 |

### rtk psql

```
rtk psql -c "SELECT * FROM users LIMIT 5"    去边框压缩表格
```

### rtk curl

```
rtk curl https://api.example.com/data        自动 JSON 检测 + schema 输出
```

### rtk wget

```
rtk wget https://example.com/file.tar.gz     去进度条
rtk wget <url> -O output.txt                 指定输出
```

---

## 10. 系统工具

### rtk ls

```
rtk ls                          目录列表
rtk ls -la                      详细列表
rtk ls -R                       递归
```

树压缩 + 聚合，压缩率 50-70%。

### rtk tree

```
rtk tree                        目录树
rtk tree -L 2 -d                深度 2，仅目录
```

### rtk read

```
rtk read file.rs                        完整读取
rtk read file.rs -l minimal             去注释
rtk read file.rs -l aggressive          去注释+函数体
rtk read file.rs -m 50                  最多 50 行
rtk read file.rs -t 20                  最后 20 行
rtk read file.rs -n                     显示行号
```

### rtk grep

```
rtk grep "pattern" src/                 搜索
rtk grep "TODO" --type rust             按文件类型
rtk grep "error" -m 200                 最大行长度
rtk grep "fn " --max-results 20         最大结果数
rtk grep "import" --match-only          仅匹配内容
rtk grep "test" -- -i -w                透传 rg 参数
```

按文件分组，压缩率 50%+。

### rtk find

```
rtk find -name "*.rs" -type f           查找文件
rtk find . -name "*.toml"               TOML 文件
```

紧凑树输出。

### rtk diff

```
rtk diff file1.txt file2.txt            文件差异
rtk diff - <(git diff)                  stdin 差异
```

### rtk json

```
rtk json data.json                      压缩 JSON
rtk json data.json --max-depth 2        深度限制
rtk json data.json --keys-only          仅键结构
```

### rtk wc

```
rtk wc -l src/*.rs                      行数
rtk wc -lwc file.txt                    行/词/字节
```

去路径和填充。

### rtk env

```
rtk env                                 环境变量（敏感值掩码）
rtk env PATH                            过滤变量名
rtk env --all                           含敏感值
```

### rtk log

```
rtk log /var/log/app.log                去重日志
rtk log                                 stdin 模式
```

### rtk deps

```
rtk deps .                              项目依赖摘要
```

### rtk summary

```
rtk summary "cargo build"               命令启发式摘要
```

### rtk smart

```
rtk smart file.rs                       2 行技术摘要（启发式）
```

---

## 11. 分析与元命令

### rtk gain — Token 节省统计

```
rtk gain                               总览
rtk gain --project                     当前项目统计
rtk gain --history                     命令历史
rtk gain --graph                       ASCII 每日图表
rtk gain --quota                       月配额估算
rtk gain --quota --tier 5x             5x 订阅层
rtk gain --daily / --weekly / --monthly 分时明细
rtk gain --failures                    解析失败日志
rtk gain --format json                 JSON 输出
rtk gain --reset                       重置统计
```

### rtk cc-economics — Claude Code 花费 vs 节省

```
rtk cc-economics                       概览
rtk cc-economics --daily               每日明细
rtk cc-economics --format csv          CSV 输出
```

### rtk discover — 发现遗漏的节省机会

```
rtk discover                           扫描当前项目
rtk discover --all-projects            全部项目
rtk discover --last 30                 最近 30 天
rtk discover --max 20                  每节最多 20 条
rtk discover --format json             JSON 输出
```

### rtk session — 会话采纳率

```
rtk session                            RTK 采纳情况
```

### rtk learn — CLI 纠正检测

```
rtk learn                              扫描错误历史
rtk learn --all-projects               全部项目
rtk learn --last 14                    最近 14 天
rtk learn --generate-rules             生成 .claude/rules/cli-corrections.md
rtk learn --min-confidence 0.7         最低置信度
rtk learn --min-occurrences 3          最低出现次数
```

### rtk telemetry — 遥测管理

```
rtk telemetry                          遥测状态/管理（RGPD/GDPR）
```

---

## 12. 配置与 Hook 管理

### rtk init — 初始化 LLM 集成

```
rtk init                               当前项目 CLAUDE.md + hooks
rtk init --global                      全局配置
rtk init --gemini                      Gemini CLI
rtk init --codex                       Codex CLI (AGENTS.md)
rtk init --copilot                     GitHub Copilot (VS Code + CLI)
rtk init --agent cursor                指定代理
rtk init --hook-only                   仅 hook，不写 RTK.md
rtk init --auto-patch                  自动修改 settings.json
rtk init --show-config                 显示当前配置
rtk init --remove                      移除 RTK 产物
rtk init --full-instructions           注入完整指令（旧模式）
```

### rtk config

```
rtk config                             显示配置
rtk config --create                    创建默认配置文件
```

### rtk rewrite — 命令重写（Hook 引擎核心）

```
rtk rewrite git status                 → rtk git status
rtk rewrite cargo test                 → rtk cargo test
rtk rewrite "lint && tsc"              链式命令
```

成功输出重写后命令（exit 0），无 RTK 等价则无输出（exit 1）。

### rtk hook — Hook 处理器

```
rtk hook claude                        Claude Code PreToolUse
rtk hook cursor                        Cursor Agent
rtk hook gemini                        Gemini CLI BeforeTool
rtk hook copilot                       Copilot preToolUse
rtk hook check --agent claude --command "git status"  干跑检查
```

### rtk hook-audit

```
rtk hook-audit                         审计指标（需 RTK_HOOK_AUDIT=1）
rtk hook-audit --since 30              最近 30 天
```

### rtk verify

```
rtk verify                             验证 hook 完整性 + TOML 内联测试
rtk verify --filter bundle-install     指定过滤器
rtk verify --ci                        任何过滤器缺测试则失败
```

### rtk trust / rtk untrust

```
rtk trust                              信任当前目录项目过滤器
rtk trust --list                       列出已信任项目
rtk untrust                            撤销信任
```

---

## 13. 通用工具

### rtk run — 执行任意命令

```
rtk run make build                     执行并追踪
rtk run -- echo "hello"                命令参数
```

### rtk proxy — 原始执行（仅追踪）

```
rtk proxy git log --oneline -20        不过滤，仅记录指标
rtk proxy npm install express          完整输出
```

### rtk pipe — Unix 管道过滤

```
cat test_output.txt | rtk pipe cargo-test     应用 cargo-test 过滤器
rtk pipe pytest < results.txt                 应用 pytest 过滤器
rtk pipe --passthrough                        透传 stdin
```

**可用过滤器名**：`cargo-test`, `pytest`, `grep`, `find`, `git-log` 等。

---

## 14. TOML 过滤器（自动匹配）

以下工具无专用 Rust 模块，通过 TOML 规则自动过滤（`rtk <tool>` 直接使用）：

| 工具 | 用途 |
|---|---|
| `make` | Make 构建输出 |
| `shellcheck` | Shell 脚本检查 |
| `pre-commit` | pre-commit hook 输出 |
| `terraform plan` / `tofu plan` | 基础设施计划 |
| `helm` | Helm 部署 |
| `docker-compose` | Docker Compose |
| `gradle` | Gradle 构建 |
| `mvn` | Maven 构建 |
| `spring-boot` | Spring Boot 启动 |
| `ansible-playbook` | Ansible 执行 |
| `gcloud` | Google Cloud CLI |
| `just` | Just 命令运行器 |
| `task` | Task 命令运行器 |
| `mise` | mise 任务运行器 |
| `brew install` | Homebrew 安装 |
| `jq` | JSON 处理 |
| `ping` | Ping 输出 |
| `df` / `du` | 磁盘使用 |
| `ps` | 进程列表 |
| `ssh` | SSH 输出 |
| `rsync` | 文件同步 |
| `sops` | 密钥管理 |
| `xcodebuild` | Xcode 构建 |
| `swift-build` | Swift 构建 |
| `mix compile/format` | Elixir 编译/格式化 |
| `biome` / `oxlint` | JS/TS linter |
| `nx` / `turbo` | Monorepo 构建器 |
| `markdownlint` / `yamllint` | Markdown/YAML lint |
| `hadolint` | Dockerfile lint |
| `stat` | 文件状态 |
| `skopeo` | 容器镜像操作 |
| `ollama` | 本地 LLM |
| `pio run` | PlatformIO 构建 |
| `shopify-theme` | Shopify 主题 |
| `quarto-render` | Quarto 渲染 |
| `fail2ban-client` | Fail2ban |
| `iptables` | 防火墙规则 |
| `systemctl status` | systemd 服务状态 |
| `jira` | Jira CLI |
| `jj` | Jujutsu VCS |
| `yadm` | Yet Another Dotfile Manager |
| `basedpyright` | Python 类型检查 |
| `ty` | ty 类型检查 |
| `uv sync` | uv 同步 |
| `poetry install` | Poetry 安装 |
| `composer install` | Composer 安装 |
| `bundle install` | Bundler 安装 |
| `liquibase` | 数据库迁移 |
| `gcc` | GCC 编译 |
| `dotnet build` | .NET 构建（TOML 备选） |
| `trunk-build` | Trunk 构建 |
| `tofu fmt/init/validate` | OpenTofu 操作 |

---

## 速查：按场景选命令

| 场景 | 命令 |
|---|---|
| 查看 git 状态 | `rtk git status` |
| 查看最近提交 | `rtk git log -10` |
| 查看代码变更 | `rtk git diff` |
| 提交代码 | `rtk git commit -m "msg"` |
| 推送代码 | `rtk git push` |
| 查看 PR | `rtk gh pr view 123` |
| Rust 构建 | `rtk cargo build` |
| Rust 测试 | `rtk cargo test` |
| Rust Lint | `rtk cargo clippy --all-targets` |
| JS Lint | `rtk lint` |
| TS 类型检查 | `rtk tsc` |
| JS 测试 | `rtk vitest` |
| E2E 测试 | `rtk playwright` |
| Python Lint | `rtk ruff check` |
| Python 测试 | `rtk pytest` |
| Python 类型 | `rtk mypy src/` |
| Go 测试 | `rtk go test ./...` |
| Go Lint | `rtk golangci-lint run` |
| .NET 构建 | `rtk dotnet build` |
| Ruby 测试 | `rtk rspec` |
| 读源码 | `rtk read file.rs -l aggressive` |
| 搜索代码 | `rtk grep "pattern" src/` |
| 查看依赖 | `rtk deps .` |
| 查看节省 | `rtk gain` |
| 初始化 RTK | `rtk init` |
| 任何命令透传 | `rtk proxy <cmd>` |
| 任意命令追踪 | `rtk run <cmd>` |

---

*基于 RTK 源码 `src/main.rs` + 64 个模块 + 59 个 TOML 过滤器生成。*
