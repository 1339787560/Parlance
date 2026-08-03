//! serviceServer (Rust 重写) 入口。
//!
//! 迁入 infoServer/serviceGroup/serviceServer/, 由 infoServer 服务组托管 (:5000)。
//! T1 阶段: path 与 status 拆分的轻量端点 (/api/config/files 零 Win32 syscall)。

mod atomic_write;
mod backup;
mod config;
mod encoding;
mod error;
mod path_check;
mod path_map;
mod proxy;
mod routes;
mod state;
mod status;
#[cfg(windows)]
mod win32;

use std::net::SocketAddr;
use std::sync::Arc;

use axum::{routing::get, Router};
// axum post 在路由链处用全路径引用 (避免顶层 import 冲突)
use tracing_subscriber::EnvFilter;

use crate::path_map::PathMap;
use crate::routes::{branches, config_file, config_files, fetch, services};
use crate::state::AppState;
use crate::status::{default_provider, StatusCache};
use std::time::Duration;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    let config_path = std::env::var("SERVICESVR_CONFIG")
        .unwrap_or_else(|_| "config.json".to_string());

    let path_map = Arc::new(PathMap::new());
    // 启动预热; 失败仅警告 (config 可能稍后到位, 请求时重试)。
    if let Err(e) = path_map.refresh(std::path::Path::new(&config_path)) {
        tracing::warn!("启动预热 config.json 失败 (稍后请求重试): {e}");
    }

    let legacy_backend = std::env::var("SERVICESVR_LEGACY_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:5099".to_string());
    let http_client = reqwest::Client::builder()
        .build()
        .unwrap_or_else(|_| reqwest::Client::new());

    let state = AppState {
        config_path: config_path.into(),
        path_map,
        status_cache: Arc::new(StatusCache::new(Duration::from_secs(10))),
        status_provider: Arc::from(default_provider()),
        legacy_backend,
        http_client,
    };

    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/api/config/files", get(config_files::list_files))
        .route("/api/config", get(config_files::get_config))
        .route("/api/fetch-title", get(fetch::fetch_title))
        // /api/svn/* 暂留 legacy 反代: svnPath 是 URL 非本地路径, 旧码语义混乱
        // (读 svnPath 未传 cwd), 待 auto-update SDD 重新设计 svn 编排。
        .route("/api/config/file/content", get(config_file::get_content))
        .route("/api/config/file/save", axum::routing::post(config_file::save_file))
        .route("/api/config/file/branches", get(branches::list_branches))
        .route(
            "/api/config/file/create_branch",
            axum::routing::post(branches::create_branch),
        )
        .route(
            "/api/config/file/switch_branch",
            axum::routing::post(branches::switch_branch),
        )
        .route(
            "/api/config/file/remove_branch",
            axum::routing::delete(branches::remove_branch),
        )
        .route("/api/services/status", get(services::list_status))
        .route("/api/config/services/running", get(services::running_services))
        // strangler: 未匹配请求反代到旧 Flask 后端 (SERVICESVR_LEGACY_URL)。
        .fallback(crate::proxy::proxy_legacy)
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 5000));
    tracing::info!("service-server listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
