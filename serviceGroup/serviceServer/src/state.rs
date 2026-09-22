//! 共享状态, 通过 axum State 注入 handler。

use crate::path_map::PathMap;
use crate::status::{ServiceStatusProvider, StatusCache};
use crate::templates::TemplateStore;
use std::path::PathBuf;
use std::sync::Arc;

#[derive(Clone)]
pub struct AppState {
    pub config_path: PathBuf,
    pub path_map: Arc<PathMap>,
    pub status_cache: Arc<StatusCache>,
    pub status_provider: Arc<dyn ServiceStatusProvider>,
    /// 发布面 (L2 run.py 的 `/api/deploy/*`), 如 http://127.0.0.1:5099。
    /// 工具自身重启委派给它 —— 发布面不在被重启目标内, 故停机窗口仍可应答。
    pub deploy_url: String,
    pub http_client: reqwest::Client,
    /// 模板存储 (SQLite); None = 未启用 (DB 路径未配置)。
    pub templates: Option<Arc<TemplateStore>>,
    /// `/static/*` 的物理根 (2026-09-22 从 legacy Flask 收编)。
    /// 权威锚点 = config.json 同级 `src` (与 `assetTool.py` 的 `ROOT/src` 同一目录);
    /// 可用 env `SERVICESVR_STATIC_DIR` 显式覆盖。None = 未解析 → 该前缀一律 404。
    pub static_root: Option<PathBuf>,
}
