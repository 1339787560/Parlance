//! 资源抓取端点 —— U4 收尾 (2026-09-22)。
//!
//! 迁移自 legacy `CustomRoute/ServiceRoute.py` 两条：
//!
//! | 路由 | 行为 |
//! |---|---|
//! | `GET /api/fetch-background?force=` | 抓背景图：**无缓存或 `force=true` 时才爬**，否则直回最新缓存 |
//! | `GET /api/fetch-metadata?url=` | 抓页面标题 + 图标，带本地缓存（按 URL 的 MD5 命名） |
//!
//! **为什么走 Python 助手**：这两条要用 `requests` + `BeautifulSoup` + **Playwright（无头
//! Chromium）**，还要用 MD5 决定图标缓存名 —— Rust 侧既没有 HTML 解析器，也没有浏览器自动化
//! 与 MD5，硬迁等于把整套抓取逻辑重写一遍并引入多个新依赖。故与 U3 同法：**HTTP 面在 Rust**
//! （参数校验 + 响应整形），**抓取与缓存在 `assetTool.py`**（各 action 逐条搬运 legacy 逻辑）。
//!
//! 附带收获：这把 SDD「N9 重依赖出启动链」要摘的**那处 playwright 抓取**从服务启动链里摘出去了
//! —— 它现在只在被请求时由独立脚本按需拉起，legacy Flask 启动不再需要 playwright 在场。
//!
//! **`/static/*` 自 2026-09-22 起由前台原生提供**：这里返回的 `/static/cache/backgrounds/...`、
//! `/static/cache/icons/...` 指向 `<legacy>/src/...`（= `assetTool.py` 的 `ROOT/src`），
//! 现由 `routes/static_files.rs` 直读同一目录发回 —— 该前缀已收编进 `proxy.rs`
//! 已前台原生（U8 后无反代）—— 写入方与读取方仍是同一个目录，闭环不变。

use crate::error::Result;
use crate::state::AppState;
use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};

/// 助手脚本名（**回落形态**：由 `SERVICESVR_PYTHON` 解释器执行）。
const HELPER_NAME: &str = "assetTool.py";

/// 冻结后的单文件助手（**优先形态**）：不依赖目标机的 Python 环境与 site-packages
/// （playwright 那套重依赖随 exe 打包）。由 `serviceServer-legacy/build_assetTool.bat`
/// 生成；是**构建产物**（`serviceServer-legacy/.gitignore` 的 `*.exe` 已忽略，不入库），
/// 随发布包投递。
///
/// ⚠ 三处清单必须同步（同名同路径）：本常量 / `make_deploy_pack.py::HELPER_EXES`（决定它
/// 进不进包）/ `CustomRoute/ServiceRoute.py::HELPER_EXES`（决定目标机走「就地替换」还是被
/// 判成 unmapped_exe 而失败）。
const HELPER_EXE: &str = "assetTool.exe";

#[derive(Deserialize)]
pub struct ForceQuery {
    pub force: Option<String>,
}

#[derive(Deserialize)]
pub struct UrlQuery {
    pub url: Option<String>,
}

fn err(status: u16, msg: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_REQUEST),
        Json(json!({ "success": false, "message": msg })),
    )
}

/// `force` 的真值口径：**只有**（忽略大小写的）`true` 算真 —— 对齐 legacy
/// `request.args.get('force', 'false').lower() == 'true'`（`1` / `yes` / 空 都算假）。
pub fn force_is_true(force: Option<&str>) -> bool {
    force
        .map(|s| s.trim().to_lowercase() == "true")
        .unwrap_or(false)
}

async fn call(
    state: &AppState,
    action: &str,
    payload: Value,
) -> Result<(StatusCode, Json<Value>)> {
    let root = match state.config_path.parent() {
        Some(p) => p.to_path_buf(),
        None => return Ok(err(500, "无法定位 legacy 目录")),
    };
    // 优先跑冻结后的单文件 exe（目标机无需 Python 环境）；缺失则回落 python 脚本
    // （开发机没跑过 build_assetTool.bat 时依旧可用）。
    let out = if root.join(HELPER_EXE).is_file() {
        crate::pybridge::call_binary(&root, HELPER_EXE, action, payload).await
    } else {
        crate::pybridge::call_helper(&root, HELPER_NAME, action, payload).await
    };
    match out {
        Ok(crate::pybridge::HelperOut::Body(b)) => Ok((StatusCode::OK, Json(b))),
        Ok(crate::pybridge::HelperOut::Error(status, msg)) => Ok(err(status, &msg)),
        Err((status, msg)) => Ok(err(status, &msg)),
    }
}

/// `GET /api/fetch-background` —— 背景图（`force=false` 且有缓存时不爬）。
pub async fn fetch_background(
    State(state): State<AppState>,
    Query(q): Query<ForceQuery>,
) -> Result<(StatusCode, Json<Value>)> {
    let force = if force_is_true(q.force.as_deref()) { "true" } else { "false" };
    call(&state, "fetch-background", json!({ "force": force })).await
}

/// `GET /api/fetch-metadata` —— 页面标题 + 图标（`url` 必填）。
pub async fn fetch_metadata(
    State(state): State<AppState>,
    Query(q): Query<UrlQuery>,
) -> Result<(StatusCode, Json<Value>)> {
    let url = q.url.unwrap_or_default();
    if url.is_empty() {
        return Ok(err(400, "缺少URL参数"));
    }
    call(&state, "fetch-metadata", json!({ "url": url })).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    /// force 真值矩阵：只有 true（任意大小写）才算真 —— 与 legacy 口径一致。
    #[rstest]
    #[case(Some("true"), true)]
    #[case(Some("TRUE"), true)]
    #[case(Some("True"), true)]
    #[case(Some(" true "), true)]
    #[case(Some("false"), false)]
    #[case(Some("1"), false)]
    #[case(Some("yes"), false)]
    #[case(Some(""), false)]
    #[case(None, false)]
    fn test_force_is_true(#[case] input: Option<&str>, #[case] expected: bool) {
        assert_eq!(force_is_true(input), expected);
    }
}
