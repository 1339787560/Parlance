//! 页面壳与静态资源端点 —— U4 迁移 (2026-09-22)。
//!
//! 迁移自 legacy `BaseRoute.py` + `ServiceRoute.py` 的 6 个页面路由与 2 个端点：
//!
//! | 路由 | 模板 | 备注 |
//! |---|---|---|
//! | `GET /` | `index.html` | legacy 还传了 `toolbar_buttons`（见下「为什么静态发就够了」） |
//! | `GET /sequence` | `sequence.html` | |
//! | `GET /deposit` | `deposit.html` | |
//! | `GET /makecard` | `makecard.html` | |
//! | `GET /serverstatus` | `ServerStatus.html` | |
//! | `GET /onlineConfigModify` | `onlineConfigModify.html` | |
//! | `GET /api/friendlinks` | — | 读 `src/extern/friendlink.json` 的 `friendlink` 数组 |
//! | `POST /api/templates/update` | — | 覆盖已有模板（`TemplateStore::update`） |
//!
//! **模板按运行时路径从 legacy 目录读**（`<legacy>/CustomRoute/templates/*.html`），
//! 不做 `include_str!` 内嵌：这些模板（`index` / `makecard` / `deposit` …）仍在被持续修改，
//! 内嵌会立刻造出**第二份真相**并漂移；而 legacy 目录在发布包里就是同一份现场文件。
//!
//! **为什么静态发就够**：实测这些模板**没有任何 Jinja 语法**（`{{` / `{%` 零命中），
//! 故 `render_template(name)` 等于原样输出；legacy `index()` 传的 `toolbar_buttons`
//! 是**死参数**（模板未使用，工具栏配置实际由 `/api/config` 下发）。
//!
//! 面包屑条由 `breadcrumb` 中间件对 `text/html` 统一注入，与本模块无关。

use crate::error::Result;
use crate::pyval::{py_int, truthy};
use crate::state::AppState;
use axum::extract::State;
use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

/// 模板目录（相对 legacy 根）。
const TEMPLATES_SUBDIR: &str = "CustomRoute/templates";

// ---------- 纯函数（可测） ----------

/// legacy 根 = `config.json` 所在目录（`SERVICESVR_CONFIG` 指向 legacy 的 config.json）。
pub fn legacy_root(config_path: &Path) -> Option<PathBuf> {
    config_path.parent().map(Path::to_path_buf)
}

/// 模板目录 = `<legacy>/CustomRoute/templates`。
pub fn templates_dir(config_path: &Path) -> Option<PathBuf> {
    legacy_root(config_path).map(|r| r.join(TEMPLATES_SUBDIR))
}

/// 抽取 friendlink 数组（缺键 / 类型不符 -> 空数组，对齐 legacy）。
pub fn extract_friendlinks(v: &Value) -> Vec<Value> {
    v.get("friendlink")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

/// `/api/templates/update` 的参数校验：legacy 为 `not all([id, name, type, data])`
/// —— 0 / 空串 / 空对象都算「缺」。
pub fn validate_template_update(body: &Value) -> std::result::Result<(i64, String, String, Value), (u16, String)> {
    if !truthy(body.get("id"))
        || !truthy(body.get("name"))
        || !truthy(body.get("type"))
        || !truthy(body.get("data"))
    {
        return Err((400, "参数不完整".into()));
    }
    let id = body.get("id").and_then(py_int).unwrap_or(0);
    let name = body.get("name").and_then(Value::as_str).unwrap_or("").to_string();
    let svc_type = body.get("type").and_then(Value::as_str).unwrap_or("").to_string();
    let data = body.get("data").cloned().unwrap_or(Value::Null);
    Ok((id, name, svc_type, data))
}

// ---------- 响应助手 ----------

fn html_response(body: String) -> Response {
    (
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        body,
    )
        .into_response()
}

fn err(status: u16, msg: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_REQUEST),
        Json(json!({ "success": false, "message": msg })),
    )
}

/// 按名读模板并发 HTML；模板不可读 -> 404（legacy 会 500 TemplateNotFound，这里给更准的状态）。
fn serve_template(config_path: &Path, name: &str) -> Response {
    let dir = match templates_dir(config_path) {
        Some(d) => d,
        None => {
            return err(500, "无法定位 legacy 目录").into_response();
        }
    };
    match std::fs::read_to_string(dir.join(name)) {
        Ok(body) => html_response(body),
        Err(e) => err(404, &format!("模板不可读: {name} ({e})")).into_response(),
    }
}

// ---------- 页面 ----------

/// `GET /` — 主页面。
pub async fn index(State(state): State<AppState>) -> Response {
    serve_template(&state.config_path, "index.html")
}

/// `GET /sequence` — 启动序列管理页。
pub async fn sequence(State(state): State<AppState>) -> Response {
    serve_template(&state.config_path, "sequence.html")
}

/// `GET /deposit` — 设置货币页。
pub async fn deposit(State(state): State<AppState>) -> Response {
    serve_template(&state.config_path, "deposit.html")
}

/// `GET /makecard` — 做牌器页。
pub async fn makecard(State(state): State<AppState>) -> Response {
    serve_template(&state.config_path, "makecard.html")
}

/// `GET /serverstatus` — 服务器状态页。
pub async fn serverstatus(State(state): State<AppState>) -> Response {
    serve_template(&state.config_path, "ServerStatus.html")
}

/// `GET /onlineConfigModify` — 在线配置修改页。
pub async fn online_config_modify(State(state): State<AppState>) -> Response {
    serve_template(&state.config_path, "onlineConfigModify.html")
}

// ---------- 数据端点 ----------

/// `GET /api/friendlinks` — 读友链数据（文件不存在 -> 空列表，与 legacy 一致）。
pub async fn friendlinks(State(state): State<AppState>) -> Result<(StatusCode, Json<Value>)> {
    let path = match legacy_root(&state.config_path) {
        Some(r) => r.join("src/extern/friendlink.json"),
        None => return Ok(err(500, "无法定位 legacy 目录")),
    };
    match std::fs::read_to_string(&path) {
        Ok(raw) => match serde_json::from_str::<Value>(&raw) {
            Ok(v) => Ok((
                StatusCode::OK,
                Json(json!({ "success": true, "friendlinks": extract_friendlinks(&v) })),
            )),
            Err(e) => Ok(err(500, &e.to_string())),
        },
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok((
            StatusCode::OK,
            Json(json!({ "success": true, "friendlinks": [] })),
        )),
        Err(e) => Ok(err(500, &e.to_string())),
    }
}

/// `POST /api/templates/update` — 覆盖已有模板；id 不存在 -> 404「模板不存在」。
pub async fn templates_update(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    let (id, name, svc_type, data) = match validate_template_update(&body) {
        Ok(v) => v,
        Err((s, m)) => return Ok(err(s, &m)),
    };
    let Some(store) = state.templates.as_ref() else {
        return Ok(err(500, "模板存储未启用"));
    };
    match store.update(id, &name, &svc_type, &data) {
        Ok(true) => Ok((
            StatusCode::OK,
            Json(json!({ "success": true, "message": "模板更新成功" })),
        )),
        Ok(false) => Ok((
            StatusCode::NOT_FOUND,
            Json(json!({ "success": false, "message": "模板不存在" })),
        )),
        Err(e) => Ok(err(500, &format!("更新模板失败: {e}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_templates_dir_resolution() {
        let cfg = Path::new("D:/legacy/config.json");
        assert_eq!(
            templates_dir(cfg),
            Some(PathBuf::from("D:/legacy/CustomRoute/templates"))
        );
        assert_eq!(legacy_root(cfg), Some(PathBuf::from("D:/legacy")));
    }

    #[test]
    fn test_extract_friendlinks() {
        // 正常
        assert_eq!(
            extract_friendlinks(&json!({"friendlink": [{"name": "a", "url": "http://a"}]})).len(),
            1
        );
        // 缺键 / 类型不符 -> 空
        assert!(extract_friendlinks(&json!({})).is_empty());
        assert!(extract_friendlinks(&json!({"friendlink": "nope"})).is_empty());
        // 空数组
        assert!(extract_friendlinks(&json!({"friendlink": []})).is_empty());
    }

    #[test]
    fn test_validate_template_update_ok() {
        let (id, name, ty, data) = validate_template_update(&json!({
            "id": 7, "name": "tpl", "type": "deposit", "data": {"a": 1}
        }))
        .unwrap();
        assert_eq!(id, 7);
        assert_eq!(name, "tpl");
        assert_eq!(ty, "deposit");
        assert_eq!(data["a"], 1);
        // 字符串 id 也接受（Python int() 语义）
        assert_eq!(
            validate_template_update(&json!({"id": "7", "name": "n", "type": "t", "data": [1]}))
                .unwrap()
                .0,
            7
        );
    }

    #[test]
    fn test_validate_template_update_missing_fields() {
        let expect = (400u16, "参数不完整".to_string());
        // 缺任一字段
        assert_eq!(
            validate_template_update(&json!({"name": "n", "type": "t", "data": {}})).unwrap_err(),
            expect
        );
        assert_eq!(
            validate_template_update(&json!({"id": 1, "type": "t", "data": {"a":1}})).unwrap_err(),
            expect
        );
        // 0 / 空串 / 空对象都算「缺」（Python falsy）
        assert_eq!(
            validate_template_update(&json!({"id": 0, "name": "n", "type": "t", "data": {"a":1}}))
                .unwrap_err(),
            expect
        );
        assert_eq!(
            validate_template_update(&json!({"id": 1, "name": "", "type": "t", "data": {"a":1}}))
                .unwrap_err(),
            expect
        );
        assert_eq!(
            validate_template_update(&json!({"id": 1, "name": "n", "type": "t", "data": {}}))
                .unwrap_err(),
            expect
        );
    }
}
