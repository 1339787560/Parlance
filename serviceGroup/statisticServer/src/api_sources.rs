//! API 来源管理路由处理：/api/sources 列表/新增 + /api/sources/{name} 更新/删除 + activate 切换。
//!
//! 所有写操作：内存态更新 → 事务落库。切换激活即时生效，无需重启。

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::sources::ApiSource;
use crate::state::AppState;

/// 响应中的来源视图（api_key 打码，避免明文回显）。
#[derive(Serialize)]
struct SourceView {
    name: String,
    api_key_masked: String,
    anthropic: String,
    openai: String,
    active: bool,
}

fn mask_key(k: &str) -> String {
    if k.is_empty() {
        return String::new();
    }
    let trimmed = k.trim();
    let n = trimmed.len();
    if n <= 8 {
        return "****".into();
    }
    format!("{}****{}", &trimmed[..4], &trimmed[n - 4..])
}

fn view(src: &ApiSource, active: bool) -> SourceView {
    SourceView {
        name: src.name.clone(),
        api_key_masked: mask_key(&src.api_key),
        anthropic: src.anthropic.clone(),
        openai: src.openai.clone(),
        active,
    }
}

/// GET /api/sources — 列表 + 当前激活名。
pub async fn list(State(state): State<std::sync::Arc<AppState>>) -> Json<Value> {
    let mgr = state.sources.read().await;
    let active = mgr.active.clone();
    let sources: Vec<Value> = mgr
        .sources
        .iter()
        .map(|s| serde_json::to_value(view(s, s.name == mgr.active)).unwrap_or(json!({})))
        .collect();
    Json(json!({
        "active": active,
        "sources": sources,
    }))
}

/// 来源写请求体。
#[derive(Deserialize)]
pub struct SourcePayload {
    pub name: Option<String>,
    #[serde(default)]
    pub api_key: String,
    #[serde(default)]
    pub anthropic: String,
    #[serde(default)]
    pub openai: String,
}

/// POST /api/sources — 新增来源。
pub async fn create(
    State(state): State<std::sync::Arc<AppState>>,
    Json(payload): Json<SourcePayload>,
) -> Response {
    let Some(name) = payload.name.as_deref().map(str::trim).filter(|s| !s.is_empty()) else {
        return (StatusCode::BAD_REQUEST, Json(json!({"error": "名称不能为空"}))).into_response();
    };
    let src = ApiSource {
        name: name.to_string(),
        api_key: payload.api_key.trim().to_string(),
        anthropic: payload.anthropic.trim().to_string(),
        openai: payload.openai.trim().to_string(),
    };

    let mut mgr = state.sources.write().await;
    if let Err(e) = mgr.create(src.clone()) {
        return (StatusCode::CONFLICT, Json(json!({"error": e}))).into_response();
    }
    // 事务落库
    let conn = state.db.lock().unwrap();
    if let Err(e) = crate::sources::save_all(&conn, &mgr) {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": format!("持久化失败: {e}")}))).into_response();
    }
    let active = mgr.active.clone();
    (StatusCode::CREATED, Json(json!({"status": "ok", "name": name, "active": active}))).into_response()
}

/// PUT /api/sources/{name} — 更新来源（名称不可改）。
pub async fn update(
    State(state): State<std::sync::Arc<AppState>>,
    Path(name): Path<String>,
    Json(payload): Json<SourcePayload>,
) -> Response {
    let mut mgr = state.sources.write().await;
    if mgr.get(&name).is_none() {
        return (StatusCode::NOT_FOUND, Json(json!({"error": format!("来源 '{}' 不存在", name)}))).into_response();
    }
    let src = ApiSource {
        name: name.clone(),
        api_key: payload.api_key.trim().to_string(),
        anthropic: payload.anthropic.trim().to_string(),
        openai: payload.openai.trim().to_string(),
    };
    if let Err(e) = mgr.update(&name, src) {
        return (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response();
    }
    let conn = state.db.lock().unwrap();
    if let Err(e) = crate::sources::save_all(&conn, &mgr) {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": format!("持久化失败: {e}")}))).into_response();
    }
    (StatusCode::OK, Json(json!({"status": "ok", "name": name}))).into_response()
}

/// DELETE /api/sources/{name} — 删除来源。
pub async fn delete(
    State(state): State<std::sync::Arc<AppState>>,
    Path(name): Path<String>,
) -> Response {
    let mut mgr = state.sources.write().await;
    if let Err(e) = mgr.delete(&name) {
        return (StatusCode::CONFLICT, Json(json!({"error": e}))).into_response();
    }
    let conn = state.db.lock().unwrap();
    if let Err(e) = crate::sources::save_all(&conn, &mgr) {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": format!("持久化失败: {e}")}))).into_response();
    }
    (StatusCode::OK, Json(json!({"status": "ok", "name": name}))).into_response()
}

/// POST /api/sources/{name}/activate — 切换当前来源。
pub async fn activate(
    State(state): State<std::sync::Arc<AppState>>,
    Path(name): Path<String>,
) -> Response {
    let mut mgr = state.sources.write().await;
    if let Err(e) = mgr.activate(&name) {
        return (StatusCode::NOT_FOUND, Json(json!({"error": e}))).into_response();
    }
    let conn = state.db.lock().unwrap();
    if let Err(e) = crate::sources::save_all(&conn, &mgr) {
        return (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": format!("持久化失败: {e}")}))).into_response();
    }
    (StatusCode::OK, Json(json!({"status": "ok", "active": name}))).into_response()
}
