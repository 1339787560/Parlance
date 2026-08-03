//! GET /api/config/file/content + POST /api/config/file/save
//!
//! 配置编辑簇核心: 读走自动探测 (BOM + strict 候选, 杜绝替换字符污染);
//! 写走 滚动备份 + 原子写 (tmp + os.rename, 失败原文件零变更, 修旧清空 bug)。

use crate::atomic_write::atomic_write_bytes;
use crate::backup::rotate_backup;
use crate::encoding;
use crate::error::{AppError, Result};
use crate::path_check::is_within_any;
use crate::state::AppState;
use axum::extract::{Query, State};
use axum::http::header;
use axum::response::IntoResponse;
use axum::Json;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

const ALLOWED_EXTS: &[&str] = &["ini", "json", "lua"];

#[derive(Deserialize)]
pub struct ContentParams {
    #[serde(rename = "filePath")]
    pub file_path: String,
}

/// GET /api/config/file/content?filePath=X
///
/// 读字节 + 自动探测编码 (忽略前端 encoding 参数, 用探测结果回填 charset 头)。
/// 旧版按用户选 encoding errors=replace 解码 -> 误选即污染, 此处根治。
pub async fn get_content(
    State(state): State<AppState>,
    Query(params): Query<ContentParams>,
) -> Result<impl IntoResponse> {
    state.path_map.refresh(&state.config_path)?;
    let path = PathBuf::from(&params.file_path);

    assert_within_roots(&state, &path)?;
    assert_allowed_ext(&path)?;
    if !path.exists() {
        return Err(AppError::NotFound);
    }

    let bytes = std::fs::read(&path)?;
    let decoded = encoding::decode(&bytes);
    Ok((
        [(
            header::CONTENT_TYPE,
            format!("text/plain; charset={}", decoded.encoding),
        )],
        decoded.content,
    ))
}

#[derive(Deserialize)]
pub struct SaveReq {
    #[serde(rename = "filePath")]
    pub file_path: String,
    pub content: String,
    pub encoding: Option<String>,
}

#[derive(Serialize)]
pub struct SaveResp {
    pub success: bool,
    pub message: String,
    pub encoding: String,
}

/// POST /api/config/file/save { filePath, content, encoding }
///
/// 流程: 路径与扩展名校验 -> 按指定编码 strict 编码 (失败报错, 原文件未动)
///       -> 滚动备份原文件 (copy) -> 原子写 (tmp + rename)。
/// 编码或写失败时原文件字节零变更 (备份是额外 copy, 不影响原文件)。
pub async fn save_file(
    State(state): State<AppState>,
    Json(req): Json<SaveReq>,
) -> Result<Json<SaveResp>> {
    state.path_map.refresh(&state.config_path)?;
    let path = PathBuf::from(&req.file_path);

    assert_within_roots(&state, &path)?;
    assert_allowed_ext(&path)?;
    if !path.exists() {
        return Err(AppError::NotFound);
    }

    let enc_name = req.encoding.as_deref().unwrap_or("utf-8");
    // 1. strict 编码到内存 (失败此处抛, 原文件未动)
    let bytes = encoding::encode(&req.content, enc_name)?;
    // 2. 滚动备份原文件 (copy, 原文件未动)
    rotate_backup(&path)?;
    // 3. 原子写 (tmp + rename, 失败原文件零变更)
    atomic_write_bytes(&path, &bytes)?;

    Ok(Json(SaveResp {
        success: true,
        message: "文件保存成功".into(),
        encoding: enc_name.into(),
    }))
}

fn assert_within_roots(state: &AppState, target: &Path) -> Result<()> {
    let roots = state.path_map.valid_roots();
    if is_within_any(target, &roots) {
        Ok(())
    } else {
        Err(AppError::Forbidden)
    }
}

fn assert_allowed_ext(path: &Path) -> Result<()> {
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();
    if ALLOWED_EXTS.iter().any(|a| *a == ext) {
        Ok(())
    } else {
        Err(AppError::InvalidExtension)
    }
}
