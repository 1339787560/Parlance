//! GET /api/config/files?serviceId=&ext= — 服务文件列表 (可选 ext 白名单过滤)。
//!
//! path 与 status 拆分后的轻量端点: 仅查 PathMap (内存) 加 listdir,
//! 零 Win32 syscall。旧版每请求全量 QueryServiceStatus -> 卡顿根因。
//!
//! ext 参数 (2026-08-04): 逗号分隔扩展名白名单 (如 "ini,json,lua"), 归一化去前导点+小写。
//! 不传 = 返全部文件 (堡垒机完全访问, 含 exe/dll/dmp/log); 传 = 仅匹配扩展名 (配置编辑页)。

use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::extract::{Query, State};
use axum::Json;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
pub struct ListParams {
    #[serde(rename = "serviceId")]
    pub service_id: String,
    /// 可选扩展名白名单 (逗号分隔, 如 "ini,json,lua"); 不传 = 返全部。
    /// 配置编辑页传 ini,json,lua; 堡垒机排查不传 = 完全访问。
    #[serde(default)]
    pub ext: Option<String>,
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

    // 可选扩展名白名单 (逗号分隔, 归一化: 去前导点 + 小写)。None = 返全部。
    let ext_filter: Option<Vec<String>> = params.ext.as_ref().map(|s| {
        s.split(',')
            .map(|e| e.trim().trim_start_matches('.').to_lowercase())
            .filter(|e| !e.is_empty())
            .collect()
    });

    let mut files = Vec::new();
    let mut read = tokio::fs::read_dir(&svc.path).await?;
    while let Some(entry) = read.next_entry().await? {
        // 完全文件访问默认列全部; ext 白名单 (配置编辑场景) 按扩展名过滤。
        // 子目录 (含 .config_history 备份目录) 由 is_file 检查跳过。
        let filename = match entry.file_name().to_str() {
            Some(n) => n.to_string(),
            None => continue,
        };
        if !entry
            .file_type()
            .await
            .map(|t| t.is_file())
            .unwrap_or(false)
        {
            continue;
        }
        let path = entry.path();
        // ext 白名单命中检查 (None = 全收, 不过滤)
        if let Some(ref allowed) = ext_filter {
            let fext = path
                .extension()
                .and_then(|e| e.to_str())
                .unwrap_or("")
                .to_lowercase();
            if !allowed.iter().any(|a| a == &fext) {
                continue;
            }
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
