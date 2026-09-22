//! Python 助手子进程桥 —— 把「HTTP 面在 Rust、数据层/抓取在 Python」的端点统一到一处。
//!
//! 两条端点族用它：`routes/money.rs`（`luaDataTool.py`：游戏库 mysql/redis/protobuf）
//! 与 `routes/assets.rs`（`assetTool.py`：requests/bs4/playwright 抓取与图标缓存）。
//!
//! **契约**（各助手脚本头有完整说明）：`python <script> <action>`，参数 JSON 走 stdin，
//! 结果 JSON 走 stdout：
//! ```text
//! {"ok": true,  "body": {...}}                        # 成功，body = 原 Flask 响应体
//! {"ok": false, "status": 400|500, "message": "..."}  # 失败，沿用原状态码与文案
//! ```
//!
//! **三条纪律（都踩过坑，别省）**：
//! 1. `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`：Windows 管道下 Python 默认落 ANSI 代码页
//!    （实测 gbk），中文 JSON 会让 Rust 侧解析失败；
//! 2. **严格** UTF-8 校验 + 解析失败带 stderr 摘要 —— 不静默替换字符，否则排障时看不到真因；
//! 3. 解释器由 `SERVICESVR_PYTHON` 指定（缺省 `python` 走 PATH）：宿主 PATH 里的 `python`
//!    不一定是带依赖的那个（本机实测 PATH → `C:\Python314` 缺 mysql，而 legacy 实跑
//!    `D:\Compiler\python`）。漏配的症状是助手回「环境不可用（缺依赖？）」。

use serde_json::Value;
use std::path::Path;
use std::process::Stdio;
use std::time::Duration;

/// 助手整体超时。抓取类端点会按需拉起无头浏览器，故给得比 DB 类宽。
const HELPER_TIMEOUT: Duration = Duration::from_secs(180);

/// 助手返回：成功带原响应体，失败带状态码与文案。
pub enum HelperOut {
    Body(Value),
    Error(u16, String),
}

/// 调一次 **python 脚本**助手：`script` 与 `action` 定位入口，`payload` 走 stdin。
///
/// `legacy_root` = 助手脚本所在目录（也是 legacy `os.getcwd()` 的等价物 —— 脚本内已改用
/// `__file__` 定位，故这里主要作为子进程 cwd）。
pub async fn call_helper(
    legacy_root: &Path,
    script: &str,
    action: &str,
    payload: Value,
) -> std::result::Result<HelperOut, (u16, String)> {
    let python = std::env::var("SERVICESVR_PYTHON").unwrap_or_else(|_| "python".to_string());
    call_program(
        legacy_root,
        python,
        vec![script.to_string(), action.to_string()],
        payload,
    )
    .await
}

/// 调一次**独立可执行**助手（如 PyInstaller 冻结出的 `assetTool.exe`）。
///
/// 与 `call_helper` 的差别只在「不经解释器」：目标机因此**不需要** Python 环境与
/// site-packages（playwright 那类重依赖随 exe 一起打包）。`exe` 传相对 legacy 根的文件名。
///
/// 注意必须拼**绝对路径**：`Command` 解析相对程序名的基准是**父进程**的 cwd，而不是下面
/// 设置的子进程 `current_dir`，直接传裸文件名会启动失败。
pub async fn call_binary(
    legacy_root: &Path,
    exe: &str,
    action: &str,
    payload: Value,
) -> std::result::Result<HelperOut, (u16, String)> {
    let program = legacy_root.join(exe).to_string_lossy().to_string();
    call_program(legacy_root, program, vec![action.to_string()], payload).await
}

/// 共用执行体：起子进程 → 喂 stdin → 收 stdout → 解析 JSON 契约（三条纪律见模块头注）。
async fn call_program(
    legacy_root: &Path,
    program: String,
    args: Vec<String>,
    payload: Value,
) -> std::result::Result<HelperOut, (u16, String)> {
    let root = legacy_root.to_path_buf();
    let body = payload.to_string();

    let task = tokio::task::spawn_blocking(
        move || -> std::result::Result<std::process::Output, String> {
            use std::io::Write;
            let mut cmd = std::process::Command::new(&program);
            for a in &args {
                cmd.arg(a);
            }
            // PYTHONIOENCODING/PYTHONUTF8 对 exe 形态无害（非 Python 会忽略），保留可让
            // 同一段代码同时服务两种形态。
            let mut child = cmd
                .current_dir(&root)
                .env("PYTHONIOENCODING", "utf-8")
                .env("PYTHONUTF8", "1")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .map_err(|e| format!("启动助手失败 (program={program}): {e}"))?;
            if let Some(stdin) = child.stdin.as_mut() {
                stdin
                    .write_all(body.as_bytes())
                    .map_err(|e| format!("写入助手 stdin 失败: {e}"))?;
            }
            drop(child.stdin.take());
            child
                .wait_with_output()
                .map_err(|e| format!("等待助手失败: {e}"))
        },
    );

    let out = match tokio::time::timeout(HELPER_TIMEOUT, task).await {
        Ok(Ok(Ok(o))) => o,
        Ok(Ok(Err(e))) => return Err((500, e)),
        Ok(Err(e)) => return Err((500, format!("助手任务失败: {e}"))),
        Err(_) => return Err((500, format!("助手超时 (>{HELPER_TIMEOUT:?})"))),
    };

    let stdout = match std::str::from_utf8(&out.stdout) {
        Ok(s) => s.trim(),
        Err(e) => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            return Err((
                500,
                format!("助手输出不是 UTF-8 ({e})；stderr: {}", truncate(&stderr, 300)),
            ));
        }
    };
    let parsed: Value = match serde_json::from_str(stdout) {
        Ok(v) => v,
        Err(e) => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            return Err((
                500,
                format!(
                    "助手返回无法解析为 JSON: {e}；stdout: {}；stderr: {}",
                    truncate(stdout, 200),
                    truncate(&stderr, 300)
                ),
            ));
        }
    };

    if parsed.get("ok").and_then(Value::as_bool) == Some(true) {
        Ok(HelperOut::Body(parsed.get("body").cloned().unwrap_or(Value::Null)))
    } else {
        let status = parsed.get("status").and_then(Value::as_u64).unwrap_or(500) as u16;
        let msg = parsed
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("助手执行失败")
            .to_string();
        Ok(HelperOut::Error(status, msg))
    }
}

fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        return s.to_string();
    }
    s.chars().take(n).collect::<String>() + "…"
}
