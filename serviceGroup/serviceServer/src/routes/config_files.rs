//! GET /api/config/files — 配置文件列表。
//!
//! path 与 status 拆分后的轻量端点: 仅查 PathMap (内存) 加 listdir,
//! 零 Win32 syscall。旧版每请求全量 QueryServiceStatus -> 卡顿根因。

use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::extract::{Query, State};
use axum::Json;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
pub struct ListParams {
    #[serde(rename = "serviceId")]
    pub service_id: String,
}

#[derive(Serialize)]
pub struct FileEntry {
    pub filename: String,
    pub path: String,
    pub full_path: String,
}

#[derive(Serialize)]
pub struct ListResp {
    pub success: bool,
    pub files: Vec<FileEntry>,
}

pub async fn list_files(
    State(state): State<AppState>,
    Query(params): Query<ListParams>,
) -> Result<Json<ListResp>> {
    // 刷新 path map (mtime 未变则跳过, 近似零成本)。
    state.path_map.refresh(&state.config_path)?;

    let svc = state
        .path_map
        .get(&params.service_id)
        .ok_or_else(|| AppError::ServiceNotFound(params.service_id.clone()))?;

    if !svc.path.exists() {
        return Err(AppError::ServiceUnavailable);
    }

    let mut files = Vec::new();
    let mut read = tokio::fs::read_dir(&svc.path).await?;
    while let Some(entry) = read.next_entry().await? {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let filename = match path.file_name().and_then(|n| n.to_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let lower = filename.to_lowercase();
        if !(lower.ends_with(".ini") || lower.ends_with(".json") || lower.ends_with(".lua")) {
            continue;
        }
        files.push(FileEntry {
            full_path: path.display().to_string(),
            path: filename.clone(),
            filename,
        });
    }
    files.sort_by(|a, b| a.filename.cmp(&b.filename));

    Ok(Json(ListResp { success: true, files }))
}

/// GET /api/config — 返回 config.json 全文 (与旧 Flask jsonify(config) 对齐)。
pub async fn get_config(State(state): State<AppState>) -> Result<Json<serde_json::Value>> {
    state.path_map.refresh(&state.config_path)?;
    if !state.config_path.exists() {
        return Err(AppError::NotFound);
    }
    let raw = std::fs::read_to_string(&state.config_path)?;
    let value: serde_json::Value = serde_json::from_str(&raw)?;
    Ok(Json(value))
}
