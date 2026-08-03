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
use crate::routes::{branches, config_file, config_files, services};
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

    let state = AppState {
        config_path: config_path.into(),
        path_map,
        status_cache: Arc::new(StatusCache::new(Duration::from_secs(10))),
        status_provider: Arc::from(default_provider()),
    };

    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/api/config/files", get(config_files::list_files))
        .route("/api/config/file/content", get(config_file::get_content))
        .route("/api/config/file/save", axum::routing::post(config_file::save_file))
        .route("/api/services/status", get(services::list_status))
        .route("/api/config/services/running", get(services::running_services))
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
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 5000));
    tracing::info!("service-server listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
