//! 共享状态, 通过 axum State 注入 handler。

use crate::path_map::PathMap;
use crate::status::{ServiceStatusProvider, StatusCache};
use std::path::PathBuf;
use std::sync::Arc;

#[derive(Clone)]
pub struct AppState {
    pub config_path: PathBuf,
    pub path_map: Arc<PathMap>,
    pub status_cache: Arc<StatusCache>,
    pub status_provider: Arc<dyn ServiceStatusProvider>,
    /// strangler 后端 (旧 Flask), 如 http://127.0.0.1:5099。
    pub legacy_backend: String,
    pub http_client: reqwest::Client,
}
