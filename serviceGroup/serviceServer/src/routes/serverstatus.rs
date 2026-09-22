//! 服务器状态页的**数据面** + 系统重启 —— 状态页迁移 (2026-09-22)。
//!
//! `/serverstatus` 的**页面壳**早已由 `routes/pages.rs` 原生发（按运行时路径读 legacy 的
//! `ServerStatus.html` 模板），但页面上的数据与按钮仍打 legacy :5099 —— 本单元补齐数据面，
//! 让该页在 legacy 退役后仍可用（U8 终态 5099 只留 `/api/deploy/*`）。
//!
//! | 路由 | 处置 |
//! |---|---|
//! | `GET  /api/serverstatus/get` | **迁 Rust**：经 `serverStatusTool.py` 助手采 psutil 指标 |
//! | `POST /api/system/restart` | **迁 Rust**：直接 `shutdown`（丢掉 legacy 的 ctypes / wmic 降级链） |
//! | `POST /api/serverstatus/stop` | **退役删除**（理由见下） |
//! | `POST /api/serverstatus/restart` | **不新建**：等价能力已在 `services::restart_service` |
//!
//! **stop 为什么是删而非迁**：它 `os._exit(0)` 停的是 Flask 自己；而首刀已裁定「工具自身
//! 不提供停止」（`routes/services.rs` 对 self 亦直接 400：「停掉自己入口即消失」）。
//! 前端「停止服务」按钮同批摘除，避免留一个永远 404 的按钮。
//!
//! **restart 为什么不新建**：原生 `POST /api/services/restart` 在 `type=self` 时委派 legacy
//! `/api/deploy/self-restart` → 宿主 restart（句柄留宿主，不做自杀式换代）—— 与之重复，
//! 故前端改打该端点、legacy 路由删除。
//!
//! **响应键保留 legacy 的 `python`**：被观测者已不是 Python 进程（legacy 观测 Flask 自身
//! `os.getpid()`，现在由 Rust 传 `std::process::id()`），但该响应形状对外可见，改名属破坏性
//! 变更 —— 故键名不动（`serverStatusTool.py` 处亦留同注），只把页面的**可见标题**改成
//! 「服务进程状态」，把误导修在用户看得见的那一处。
//!
//! **⚠ `/api/system/restart` 是危险原语**：LAN 上无鉴权即可重启整台机器（legacy 亦如此，
//! 非本次引入）。本次按「不砍现场既有运维能力」保留原行为，是否加 token / 收窄到 CLI
//! 属后续口径（已记入 SDD 待办）。

use crate::error::Result;
use crate::state::AppState;
use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use serde_json::{json, Value};

/// 助手脚本名（与 `serviceServer-legacy/` 同目录，随发布包发布）。
const HELPER_NAME: &str = "serverStatusTool.py";

fn err(status: u16, msg: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_REQUEST),
        Json(json!({ "success": false, "message": msg })),
    )
}

/// `/api/system/restart` 的实际命令（平台分支抽成纯函数，便于单测）。
///
/// Windows 用 `shutdown /r /t 0 /f` —— 即 legacy 三连降级里**实际生效的那条**；它的
/// ctypes `ShellExecuteW(runas)` 试探与 `wmic` 兜底一并丢掉（`wmic` 已从 Win11 移除，
/// 本仓 [`避坑清单`] 早有记录，那条是死代码）。非 Windows 退 `shutdown -r now`
/// （Mac 无 serviceServer 二进制，仅为保编译与单测）。
pub fn restart_command() -> (&'static str, &'static [&'static str]) {
    #[cfg(windows)]
    {
        ("shutdown", &["/r", "/t", "0", "/f"])
    }
    #[cfg(not(windows))]
    {
        ("shutdown", &["-r", "now"])
    }
}

/// `GET /api/serverstatus/get` —— 系统指标 + 服务进程指标。
///
/// 响应形状 `{success, system:{12 字段}, python:{12 字段}}` —— 与 legacy 完全一致
/// （键名仍叫 `python`，见模块头注）。指标采集全在 `serverStatusTool.py`（psutil），
/// 前台只做转发与错误整形。
pub async fn get(State(state): State<AppState>) -> Result<(StatusCode, Json<Value>)> {
    let root = match state.config_path.parent() {
        Some(p) => p.to_path_buf(),
        None => return Ok(err(500, "无法定位 legacy 目录")),
    };
    // 被观测进程 = 本进程（Rust 前台）：助手是短命子进程，观测它自己没有意义。
    let payload = json!({ "pid": std::process::id() });
    match crate::pybridge::call_helper(&root, HELPER_NAME, "snapshot", payload).await {
        Ok(crate::pybridge::HelperOut::Body(b)) => Ok((StatusCode::OK, Json(b))),
        Ok(crate::pybridge::HelperOut::Error(status, msg)) => Ok(err(status, &msg)),
        Err((status, msg)) => Ok(err(status, &msg)),
    }
}

/// `POST /api/system/restart` —— 重启整台机器。
///
/// 同步等 `shutdown` 返回码（与 legacy `subprocess.run(timeout=10)` 口径一致），失败文案
/// 沿用 legacy 的「请确保以管理员身份运行此服务」。走 `spawn_blocking`，不占 tokio 工作线程。
pub async fn system_restart() -> Result<(StatusCode, Json<Value>)> {
    let res = tokio::task::spawn_blocking(|| {
        let (cmd, args) = restart_command();
        std::process::Command::new(cmd).args(args).status()
    })
    .await;

    match res {
        Ok(Ok(st)) if st.success() => Ok((
            StatusCode::OK,
            Json(json!({ "success": true, "message": "系统正在重启..." })),
        )),
        Ok(Ok(st)) => Ok(err(
            500,
            &format!("无法执行重启命令（shutdown 退出码 {st}），请确保以管理员身份运行此服务"),
        )),
        Ok(Err(e)) => Ok(err(
            500,
            &format!("无法执行重启命令，请确保以管理员身份运行此服务: {e}"),
        )),
        Err(e) => Ok(err(500, &format!("重启任务失败: {e}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 重启命令矩阵：Windows 必须是 `/r /t 0 /f`（legacy 实际生效的那条），且不再依赖
    /// wmic / powershell / ctypes 三连降级（wmic 已从 Win11 移除）。
    #[test]
    fn test_restart_command() {
        let (cmd, args) = restart_command();
        assert_eq!(cmd, "shutdown");

        #[cfg(windows)]
        assert_eq!(args.to_vec(), vec!["/r", "/t", "0", "/f"]);
        #[cfg(not(windows))]
        assert_eq!(args.to_vec(), vec!["-r", "now"]);

        assert!(!args.iter().any(|a| a.to_lowercase().contains("wmic")));
    }
}
