//! GET /api/spideorder/get + POST /api/spideorder/save + POST /api/spideorder/execute
//!
//! 对齐 legacy CustomRoute/ServiceRoute.py spideorder 三路由:
//!   get     -> {success, commands:[...]}          (config.json spideOrder 数组)
//!   save    -> {commands:[...]} -> {success,message}
//!   execute -> 后台逐条 spawn `python spideOnlineLog.py <cmd>` -> 立即返
//!              {success,message:"命令执行已开始"}
//!
//! execute 走子进程 (对齐 legacy Popen): spideOnlineLog.py 是独立 CLI (argparse),
//! OSS 源依赖 oss2/CredsManager, 整块嵌 PyO3 不值; 脚本 + CommonTools 与
//! service-server.exe 同目录放置 (config.yaml cwd), Rust 侧只做编排 + 300s 超时。

use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::time::Duration;

const COMMAND_TIMEOUT: Duration = Duration::from_secs(300);
/// legacy Popen 用的解释器名 (走 PATH, 与 legacy 一致)。
const PYTHON: &str = "python";

#[derive(Deserialize)]
pub struct SaveReq {
    pub commands: Vec<String>,
}

/// GET /api/spideorder/get — 读 config.json spideOrder 数组。
pub async fn get_config(State(state): State<AppState>) -> Result<(StatusCode, Json<Value>)> {
    let config = match crate::routes::read_config_value(&state.config_path) {
        Ok(v) => v,
        Err(AppError::NotFound) => {
            return Ok((
                StatusCode::NOT_FOUND,
                Json(json!({ "success": false, "message": "配置文件不存在" })),
            ))
        }
        Err(e) => return Err(e),
    };
    let commands = extract_commands(&config);
    Ok((
        StatusCode::OK,
        Json(json!({ "success": true, "commands": commands })),
    ))
}

/// POST /api/spideorder/save — 过滤空命令后写回 config.json (原子写 + 滚动备份)。
pub async fn save_config(
    State(state): State<AppState>,
    Json(req): Json<SaveReq>,
) -> Result<(StatusCode, Json<Value>)> {
    let mut config = match crate::routes::read_config_value(&state.config_path) {
        Ok(v) => v,
        Err(AppError::NotFound) => {
            return Ok((
                StatusCode::NOT_FOUND,
                Json(json!({ "success": false, "message": "配置文件不存在" })),
            ))
        }
        Err(e) => return Err(e),
    };
    let commands = filter_commands(req.commands);
    config["spideOrder"] = Value::Array(commands.iter().cloned().map(Value::String).collect());
    crate::routes::write_config_value(&state.config_path, &config)?;
    Ok((
        StatusCode::OK,
        Json(json!({ "success": true, "message": "配置保存成功" })),
    ))
}

/// POST /api/spideorder/execute — 后台逐条 spawn spideOnlineLog.py, 立即返。
pub async fn execute(
    State(state): State<AppState>,
) -> Result<(StatusCode, Json<Value>)> {
    let config = match crate::routes::read_config_value(&state.config_path) {
        Ok(v) => v,
        Err(AppError::NotFound) => {
            return Ok((
                StatusCode::NOT_FOUND,
                Json(json!({ "success": false, "message": "配置文件不存在" })),
            ))
        }
        Err(e) => return Err(e),
    };
    let commands = extract_commands(&config);
    if commands.is_empty() {
        return Ok((
            StatusCode::BAD_REQUEST,
            Json(json!({ "success": false, "message": "没有配置执行命令" })),
        ));
    }
    // 脚本必须与 exe 同目录 (config.yaml cwd), 缺失时报错而非后台静默失败。
    let cwd = std::env::current_dir().map_err(|e| AppError::Io(e))?;
    if !cwd.join("spideOnlineLog.py").exists() {
        return Ok((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({
                "success": false,
                "message": format!("未找到 spideOnlineLog.py ({}), 请确认与 service-server.exe 同目录", cwd.display())
            })),
        ));
    }
    for cmd in &commands {
        spawn_spideorder(cwd.clone(), cmd.clone());
    }
    Ok((
        StatusCode::OK,
        Json(json!({ "success": true, "message": "命令执行已开始" })),
    ))
}

/// 后台跑一条命令: `python spideOnlineLog.py <args>`, 300s 超时 kill。
/// legacy 用 daemon thread + communicate(timeout=300), Rust 用 tokio task + timeout。
/// stdout/stderr 用 inherit 汇入 server 自身日志 (避免管道背压死锁, 且输出可查)。
fn spawn_spideorder(cwd: std::path::PathBuf, cmd: String) {
    tokio::task::spawn(async move {
        let args: Vec<&str> = cmd.split_whitespace().collect();
        let mut child = match tokio::process::Command::new(PYTHON)
            .arg("spideOnlineLog.py")
            .args(&args)
            .current_dir(&cwd)
            .stdout(std::process::Stdio::inherit())
            .stderr(std::process::Stdio::inherit())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => {
                tracing::warn!("spideorder spawn 失败 (cmd={cmd}): {e}");
                return;
            }
        };
        match tokio::time::timeout(COMMAND_TIMEOUT, child.wait()).await {
            Ok(Ok(st)) => {
                tracing::info!("spideorder 完成 (cmd={cmd}) exit={:?}", st.code());
            }
            Ok(Err(e)) => {
                tracing::warn!("spideorder 等待失败 (cmd={cmd}): {e}");
            }
            Err(_) => {
                let _ = child.kill().await;
                let _ = child.wait().await;
                tracing::warn!("spideorder 超时 kill (cmd={cmd})");
            }
        }
    });
}

// ---- 纯函数 (可测) ----

/// 从 config.json Value 提取 spideOrder 字符串数组 (缺省 -> 空)。
pub fn extract_commands(config: &Value) -> Vec<String> {
    config
        .get("spideOrder")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

/// 过滤空命令: trim + 去空 (对齐 legacy `[cmd.strip() for cmd in commands if cmd.strip()]`)。
pub fn filter_commands(commands: Vec<String>) -> Vec<String> {
    commands
        .into_iter()
        .map(|c| c.trim().to_string())
        .filter(|c| !c.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::json;

    #[rstest]
    #[case::no_key(json!({}), vec![])]
    #[case::empty(json!({"spideOrder": []}), vec![])]
    #[case::two(json!({"spideOrder": ["-p zgda", "-r X --block"]}), vec!["-p zgda", "-r X --block"])]
    fn test_extract_commands(#[case] config: Value, #[case] expected: Vec<&str>) {
        assert_eq!(extract_commands(&config), expected);
    }

    #[rstest]
    #[case::mixed(vec!["  -p zgda ".into(), "   ".into(), "".into(), "-r X".into()], vec!["-p zgda", "-r X"])]
    #[case::all_blank(vec!["  ".into(), "".into()], vec![])]
    fn test_filter_commands(#[case] input: Vec<String>, #[case] expected: Vec<&str>) {
        assert_eq!(filter_commands(input), expected);
    }
}
