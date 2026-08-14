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
mod ports_probe;
mod proxy;
mod routes;
mod state;
mod status;
mod svc_control;
mod templates;
#[cfg(windows)]
mod win32;

use std::net::SocketAddr;
use std::sync::Arc;

use axum::{routing::get, Router};
// axum post 在路由链处用全路径引用 (避免顶层 import 冲突)
use tracing_subscriber::EnvFilter;

use crate::path_map::PathMap;
use crate::routes::{branches, config_file, config_files, fetch, recorder, records, services, spideorder, templates as tpl};
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

    // 模板 DB: env SERVICESVR_TEMPLATES_DB 优先, 否则 config 同级 CustomRoute/templates.db
    // (复用 legacy 库, 已有模板不丢)。
    let templates_db = std::env::var("SERVICESVR_TEMPLATES_DB").ok();
    let templates = match templates_db {
        Some(p) => match crate::templates::TemplateStore::open(std::path::Path::new(&p)) {
            Ok(s) => Some(Arc::new(s)),
            Err(e) => {
                tracing::warn!("模板 DB 打开失败 ({p}): {e}; /api/templates/* 将 500");
                None
            }
        },
        None => {
            let cfg = std::path::Path::new(&config_path);
            let p = cfg
                .parent()
                .map(|d| d.join("CustomRoute").join("templates.db"))
                .unwrap_or_else(|| std::path::PathBuf::from("CustomRoute/templates.db"));
            match crate::templates::TemplateStore::open(&p) {
                Ok(s) => Some(Arc::new(s)),
                Err(e) => {
                    tracing::warn!("模板 DB 打开失败 ({}): {e}; /api/templates/* 将 500", p.display());
                    None
                }
            }
        }
    };

    let state = AppState {
        config_path: config_path.into(),
        path_map,
        status_cache: Arc::new(StatusCache::new(Duration::from_secs(10))),
        status_provider: Arc::from(default_provider()),
        legacy_backend,
        http_client,
        templates,
    };

    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/recorder", get(recorder::page))
        .route("/recorder/demo", get(recorder::demo))
        .route("/recorder/mj_color0.png", get(recorder::sprite))
        // 复盘器数据源 (SDD running/四川麻将复盘器-数据源): 三类源统一 /api/record/*
        .route("/api/record/sources", get(records::sources))
        .route("/api/record/list", get(records::list))
        .route("/api/record/get", get(records::get))
        .route("/api/record/scan_rounds", get(records::scan_rounds))
        .route("/api/config/files", get(config_files::list_files))
        .route("/api/config", get(config_files::get_config))
        .route("/api/fetch-title", get(fetch::fetch_title))
        // /api/svn/* 暂留 legacy 反代: svnPath 是 URL 非本地路径, 旧码语义混乱
        // (读 svnPath 未传 cwd), 待 auto-update SDD 重新设计 svn 编排。
        .route("/api/config/file/content", get(config_file::get_content))
        .route("/api/config/file/download", get(config_file::download_file))
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
        .route(
            "/api/services/start",
            axum::routing::post(services::start_service),
        )
        .route(
            "/api/services/stop",
            axum::routing::post(services::stop_service),
        )
        .route(
            "/api/services/restart",
            axum::routing::post(services::restart_service),
        )
        .route(
            "/api/services/delete",
            axum::routing::post(services::delete_service),
        )
        .route("/api/templates/get", get(tpl::get))
        .route("/api/templates/save", axum::routing::post(tpl::save))
        .route("/api/templates/delete", axum::routing::post(tpl::delete))
        // spideorder 簇: config 读写 + 后台执行 spideOnlineLog.py (脚本与 exe 同目录)。
        .route("/api/spideorder/get", get(spideorder::get_config))
        .route("/api/spideorder/save", axum::routing::post(spideorder::save_config))
        .route("/api/spideorder/execute", axum::routing::post(spideorder::execute))
        // services 控制簇剩余: deploy(sc create) + start-all + update(multipart 热更新)。
        .route("/api/services/deploy", axum::routing::post(services::deploy_service))
        .route("/api/services/start-all", axum::routing::post(services::start_all_services))
        .route(
            "/api/services/update",
            axum::routing::post(services::update_service)
                .layer(axum::extract::DefaultBodyLimit::max(200 * 1024 * 1024)),
        )
        // strangler: 未匹配请求反代到旧 Flask 后端 (SERVICESVR_LEGACY_URL)。
        .fallback(crate::proxy::proxy_legacy)
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 5000));
    tracing::info!("service-server listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
