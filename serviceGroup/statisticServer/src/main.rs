//! statistic-server (Rust 重写)：DeepSeek 代理统计服务。
//!
//! 透明代理（Anthropic / OpenAI 双格式）+ Token 统计看板 + SSE 实时推送。

mod model;
mod proxy;
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
use axum::routing::{any, get};
use axum::{Json, Router};
use serde_json::json;
use tower_http::cors::CorsLayer;
use tower_http::services::ServeDir;

use state::{AppState, Targets};

/// 当前 ISO 时间戳。
fn now_iso() -> String {
    chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%.3f").to_string()
}

/// 健康检查（对齐旧 /health）。
async fn health(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    Json(json!({
        "status": "ok",
        "anthropic_target": state.targets.anthropic,
        "openai_target": state.targets.openai,
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
    let (sse_tx, _) = sse::new_channel();
    let state = Arc::new(AppState::new(
        Arc::new(Mutex::new(conn)),
        sse_tx,
        Targets {
            anthropic: anthropic_target.clone(),
            openai: openai_target.clone(),
        },
        static_dir,
    ));

    if api_key.is_empty() {
        tracing::warn!("DEEPSEEK_API_KEY not set — proxy will 500 until configured");
    }

    let app = build_router(state);
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", port))
        .await
        .expect("bind port");
    tracing::info!("statistic-server listening on :{}", port);
    tracing::info!("  Anthropic → {}", anthropic_target);
    tracing::info!("  OpenAI    → {}", openai_target);
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
