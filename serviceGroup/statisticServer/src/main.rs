//! statistic-server (Rust 重写)：DeepSeek 代理统计服务。
//!
//! 透明代理（Anthropic / OpenAI 双格式）+ Token 统计看板 + SSE 实时推送。

mod api_sources;
mod model;
mod proxy;
mod sources;
mod sse;
mod state;
mod stats;
mod stats_internal;
mod store;

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use axum::extract::State;
use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{any, get, post, put};
use axum::{Json, Router};
use serde_json::json;
use tower_http::cors::CorsLayer;
use tower_http::services::ServeDir;

use sources::{ApiSource, SourceManager, SourcesHandle};
use state::AppState;

/// 当前 ISO 时间戳。
fn now_iso() -> String {
    chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%.3f").to_string()
}

/// 健康检查（对齐旧 /health，报告当前激活来源的 target）。
async fn health(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let mgr = state.sources.read().await;
    let active = mgr.active.clone();
    let (anthropic, openai) = match mgr.active_source() {
        Some(s) => (s.anthropic.clone(), s.openai.clone()),
        None => (String::new(), String::new()),
    };
    Json(json!({
        "status": "ok",
        "active_source": active,
        "anthropic_target": anthropic,
        "openai_target": openai,
        "sources_count": mgr.sources.len(),
    }))
}

/// /api/events SSE 实时流。
async fn events(State(state): State<Arc<AppState>>) -> Response {
    let rx = state.sse.subscribe();
    sse::sse_stream(rx).into_response()
}

/// 构建路由。
fn build_router(state: Arc<AppState>) -> Router {
    let static_dir = state.static_dir.clone();
    Router::new()
        .route("/health", get(health))
        .route("/api/events", get(events))
        .route("/api/refresh", get(stats::refresh))
        .route("/api/stats", get(stats::aggregate))
        .route("/api/stats/detail", get(stats::detail))
        .route("/api/stats/daily", get(stats::daily))
        .route("/api/stats/tasks", get(stats::tasks))
        .route("/api/stats/session/advice", get(stats::session_advice))
        .route("/api/sources", get(api_sources::list).post(api_sources::create))
        .route("/api/sources/{name}", put(api_sources::update).delete(api_sources::delete))
        .route("/api/sources/{name}/activate", post(api_sources::activate))
        .route("/", get(index))
        .nest_service("/static", ServeDir::new(static_dir))
        .route("/{*path}", any(proxy::proxy))
        .layer(CorsLayer::permissive())
        .with_state(state)
}

/// 根路径：看板 index.html（对齐旧 FileResponse）。
async fn index(State(state): State<Arc<AppState>>) -> Response {
    let idx = state.static_dir.join("index.html");
    match tokio::fs::read(&idx).await {
        Ok(bytes) => (
            StatusCode::OK,
            [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
            bytes,
        )
            .into_response(),
        Err(_) => Json(json!({"status": "proxy_ready"})).into_response(),
    }
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::DEBUG)
        .init();

    // ---- 配置 ----
    let api_key = std::env::var("DEEPSEEK_API_KEY").unwrap_or_default();
    let anthropic_target = std::env::var("ANTHROPIC_TARGET")
        .unwrap_or_else(|_| "https://api.deepseek.com/anthropic".to_string());
    let openai_target = std::env::var("OPENAI_TARGET")
        .unwrap_or_else(|_| "https://api.deepseek.com/v1".to_string());
    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(5002);
    let db_path = PathBuf::from(
        std::env::var("DB_PATH").unwrap_or_else(|_| "stats.db".to_string()),
    );

    let static_dir = PathBuf::from("static");

    // ---- 初始化 ----
    let conn = store::init_db(&db_path).expect("init db");

    // 来源管理：优先从 DB 恢复；首次启动（空库）用环境变量种子一个默认来源
    let (sources, active) = sources::load(&conn).expect("load sources");
    let sources: SourcesHandle = Arc::new(tokio::sync::RwLock::new(if sources.is_empty() {
        tracing::info!("sources 表为空 — 从环境变量种子默认来源");
        let default = ApiSource {
            name: "env".into(),
            api_key,
            anthropic: anthropic_target.clone(),
            openai: openai_target.clone(),
        };
        SourceManager::new(vec![default], "env".into())
    } else {
        let active = if active.is_empty() {
            sources.first().map(|s| s.name.clone()).unwrap_or_default()
        } else {
            active
        };
        SourceManager::new(sources, active)
    }));

    let (sse_tx, _) = sse::new_channel();
    let state = Arc::new(AppState::new(
        Arc::new(Mutex::new(conn)),
        sse_tx,
        sources,
        static_dir,
    ));

    {
        let mgr = state.sources.read().await;
        if mgr.active_api_key().is_empty() {
            tracing::warn!("激活来源未配置 api_key — 客户端未透传 key 时代理将 500");
        }
        tracing::info!("API 来源 {} 个, 激活: {}", mgr.sources.len(), mgr.active);
    }

    let app = build_router(state);
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", port))
        .await
        .expect("bind port");
    tracing::info!("statistic-server listening on :{}", port);
    axum::serve(listener, app).await.expect("serve");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn now_iso_format() {
        let s = now_iso();
        assert!(s.contains('T'));
        assert!(s.len() >= 19);
    }
}
