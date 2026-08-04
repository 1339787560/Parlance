//! GET /api/config/file/content + GET /api/config/file/download + POST /api/config/file/save
//!
//! 配置编辑簇核心:
//! - 读 / 下载: 任意文件 (服务路径沙箱内, 不限扩展名)。读走自动探测编码 (BOM + strict
//!   候选, 杜绝替换字符污染); 下载走原始字节流 (二进制 exe/dll/dmp 兜底)。
//! - 写: 仅配置文件 (ini/json/lua), 滚动备份 + 原子写 (失败原文件零变更)。

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
    // 读不限扩展名 (完全文件访问): 文本走编码探测, 二进制走 latin-1 兜底 (不崩, 乱码可接受)。
    // 大二进制文件 (exe/dll/dmp) 走 /api/config/file/download 拿原始字节流。
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

/// GET /api/config/file/download?filePath=X
///
/// 任意文件下载 (二进制兜底): exe/dll/dmp/zip 走原始字节流, Content-Disposition
/// attachment 触发浏览器下载。服务路径沙箱内, 不限扩展名 (与读一致)。
/// 读上限 200MB 防 OOM (与 update multipart 上限对齐, 超大文件改流式再议)。
pub async fn download_file(
    State(state): State<AppState>,
    Query(params): Query<ContentParams>,
) -> Result<impl IntoResponse> {
    state.path_map.refresh(&state.config_path)?;
    let path = PathBuf::from(&params.file_path);

    assert_within_roots(&state, &path)?;
    if !path.is_file() {
        return Err(AppError::NotFound);
    }

    // 上限保护: 超 200MB 拒绝 (防 OOM; 堡垒机超大文件改流式再议)。
    const MAX_DOWNLOAD_BYTES: u64 = 200 * 1024 * 1024;
    let meta = std::fs::metadata(&path)?;
    if meta.len() > MAX_DOWNLOAD_BYTES {
        return Err(AppError::TooLarge(meta.len()));
    }

    let bytes = std::fs::read(&path)?;
    let filename = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("file")
        .to_string();

    // RFC 5987: filename*=UTF-8''<pct> 浏览器优先认; filename= ASCII fallback 兜底。
    // header value 含中文会 panic (HeaderValue::from_str 拒绝非 ASCII), 故 pct-encode。
    let disposition = format!(
        "attachment; filename=\"file\"; filename*=UTF-8''{}",
        pct_encode_filename(&filename)
    );

    Ok((
        [
            (header::CONTENT_TYPE, "application/octet-stream".to_string()),
            (header::CONTENT_DISPOSITION, disposition),
        ],
        bytes,
    ))
}

/// RFC 3986 percent-encode 文件名 (header value 仅允许 ASCII, 中文文件名编码后传输)。
fn pct_encode_filename(name: &str) -> String {
    let mut out = String::with_capacity(name.len() * 3);
    for &b in name.as_bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
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
/// 写仅限配置文件扩展名 (ini/json/lua, 见 ALLOWED_EXTS); 读与下载不限。
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
