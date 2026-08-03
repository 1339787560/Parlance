//! 配置文件分支管理 (命名变体, 不同于 backup.rs 的滚动备份)。
//!
//! GET    /api/config/file/branches        列 {name}_*.{ext} 分支文件
//! POST   /api/config/file/create_branch   建 {name}_{branch}.{ext}
//! POST   /api/config/file/switch_branch   分支切换为主文件 (当前入 remove/ 暂存)
//! DELETE /api/config/file/remove_branch   删分支文件

use crate::error::{AppError, Result};
use crate::routes::checks::{assert_allowed_ext, assert_within_roots};
use crate::state::AppState;
use axum::extract::{Query, State};
use axum::Json;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Deserialize)]
pub struct FilePathQuery {
    #[serde(rename = "filePath")]
    pub file_path: String,
}

#[derive(Serialize)]
pub struct BranchesResp {
    pub success: bool,
    pub current_file: String,
    pub branch_files: Vec<String>,
}

/// GET /api/config/file/branches — 列同目录下 {name}_*.{ext} 分支文件。
pub async fn list_branches(
    State(state): State<AppState>,
    Query(q): Query<FilePathQuery>,
) -> Result<Json<BranchesResp>> {
    let path = resolve_and_check(&state, &q.file_path)?;
    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    let stem = file_stem(&path);
    let ext_with_dot = ext_with_dot(&path);

    let prefix = format!("{stem}_");
    let mut branch_files = Vec::new();
    if let Ok(read) = std::fs::read_dir(dir) {
        for entry in read.filter_map(|e| e.ok()) {
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with(&prefix) && name.ends_with(&ext_with_dot) {
                branch_files.push(name);
            }
        }
    }
    branch_files.sort();
    Ok(Json(BranchesResp {
        success: true,
        current_file: file_name_str(&path).into(),
        branch_files,
    }))
}

#[derive(Deserialize)]
pub struct CreateBranchReq {
    #[serde(rename = "filePath")]
    pub file_path: String,
    pub branch_name: String,
    pub content: Option<String>,
}

#[derive(Serialize)]
pub struct CreateBranchResp {
    pub success: bool,
    pub message: String,
    pub branch_file: String,
}

/// POST /api/config/file/create_branch — 建命名分支 (content 缺省则复制主文件)。
pub async fn create_branch(
    State(state): State<AppState>,
    Json(req): Json<CreateBranchReq>,
) -> Result<Json<CreateBranchResp>> {
    let path = resolve_and_check(&state, &req.file_path)?;
    assert_allowed_ext(&path)?;
    validate_branch_name(&req.branch_name)?;

    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    let stem = file_stem(&path);
    let ext_with_dot = ext_with_dot(&path);
    let branch_filename = format!("{stem}_{}{ext_with_dot}", req.branch_name);
    let branch_path = dir.join(&branch_filename);
    if branch_path.exists() {
        return Err(AppError::BranchExists);
    }

    let content = match req.content {
        Some(c) => c,
        None => std::fs::read_to_string(&path)?,
    };
    std::fs::write(&branch_path, content)?;
    Ok(Json(CreateBranchResp {
        success: true,
        message: "分支文件创建成功".into(),
        branch_file: branch_filename,
    }))
}

#[derive(Deserialize)]
pub struct SwitchReq {
    #[serde(rename = "filePath")]
    pub file_path: String,
    pub branch_name: String,
}

#[derive(Serialize)]
pub struct SwitchResp {
    pub success: bool,
    pub message: String,
    pub current_file: String,
}

/// POST /api/config/file/switch_branch — 分支切换为主文件。
///
/// 流程: 当前主文件移入 remove/ 暂存 -> 复制分支为主文件 -> 字节比对验证
///       -> 失败则从 remove/ 回滚主文件。
pub async fn switch_branch(
    State(state): State<AppState>,
    Json(req): Json<SwitchReq>,
) -> Result<Json<SwitchResp>> {
    let path = resolve_and_check(&state, &req.file_path)?;
    assert_allowed_ext(&path)?;
    validate_branch_name(&req.branch_name)?;

    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    let stem = file_stem(&path);
    let ext_with_dot = ext_with_dot(&path);
    let target_path = dir.join(format!("{stem}_{}{ext_with_dot}", req.branch_name));
    if !target_path.exists() {
        return Err(AppError::NotFound);
    }

    let remove_dir = dir.join("remove");
    std::fs::create_dir_all(&remove_dir)?;
    let removed_path = remove_dir.join(file_name_str(&path));
    // 暂存区同名残留清掉 (上次切换遗留)。
    if removed_path.exists() {
        let _ = std::fs::remove_file(&removed_path);
    }
    std::fs::rename(&path, &removed_path)?;

    // 复制分支为主文件; 失败回滚。
    if std::fs::copy(&target_path, &path).is_err() {
        let _ = std::fs::rename(&removed_path, &path);
        return Err(AppError::Io(std::io::Error::new(
            std::io::ErrorKind::Other,
            "切换分支失败: 无法创建目标文件",
        )));
    }

    // 字节比对验证; 不一致回滚。
    let target_bytes = std::fs::read(&target_path).unwrap_or_default();
    let main_bytes = std::fs::read(&path).unwrap_or_default();
    if target_bytes != main_bytes {
        let _ = std::fs::rename(&removed_path, &path);
        return Err(AppError::Io(std::io::Error::new(
            std::io::ErrorKind::Other,
            "切换分支失败: 文件内容验证失败",
        )));
    }

    Ok(Json(SwitchResp {
        success: true,
        message: "分支切换成功".into(),
        current_file: file_name_str(&path).into(),
    }))
}

#[derive(Deserialize)]
pub struct RemoveBranchQuery {
    #[serde(rename = "filePath")]
    pub file_path: String,
    #[serde(rename = "branchName")]
    pub branch_name: String,
}

#[derive(Serialize)]
pub struct RemoveResp {
    pub success: bool,
    pub message: String,
}

/// DELETE /api/config/file/remove_branch — 删分支文件。
pub async fn remove_branch(
    State(state): State<AppState>,
    Query(q): Query<RemoveBranchQuery>,
) -> Result<Json<RemoveResp>> {
    let path = resolve_and_check(&state, &q.file_path)?;
    assert_allowed_ext(&path)?;
    validate_branch_name(&q.branch_name)?;

    let dir = path.parent().unwrap_or_else(|| Path::new("."));
    let stem = file_stem(&path);
    let ext_with_dot = ext_with_dot(&path);
    let branch_path = dir.join(format!("{stem}_{}{ext_with_dot}", q.branch_name));
    if !branch_path.exists() {
        return Err(AppError::NotFound);
    }
    std::fs::remove_file(&branch_path)?;
    Ok(Json(RemoveResp {
        success: true,
        message: "分支文件删除成功".into(),
    }))
}

// ---- helpers ----

fn resolve_and_check(state: &AppState, file_path: &str) -> Result<PathBuf> {
    state.path_map.refresh(&state.config_path)?;
    let path = PathBuf::from(file_path);
    assert_within_roots(state, &path)?;
    if !path.exists() {
        return Err(AppError::NotFound);
    }
    Ok(path)
}

fn validate_branch_name(name: &str) -> Result<()> {
    let ok = !name.is_empty()
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-');
    if ok {
        Ok(())
    } else {
        Err(AppError::InvalidBranchName)
    }
}

fn file_stem(p: &Path) -> &str {
    p.file_stem().and_then(|s| s.to_str()).unwrap_or("")
}

fn ext_with_dot(p: &Path) -> String {
    p.extension()
        .and_then(|e| e.to_str())
        .map(|e| format!(".{e}"))
        .unwrap_or_default()
}

fn file_name_str(p: &Path) -> &str {
    p.file_name().and_then(|n| n.to_str()).unwrap_or("")
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    /// 分支名白名单矩阵: 仅字母数字下划线连字符。
    #[rstest]
    #[case::alnum("dev", true)]
    #[case::with_dash("dev-1", true)]
    #[case::with_underscore("dev_1", true)]
    #[case::mixed("Cfg_2026", true)]
    #[case::empty("", false)]
    #[case::space("dev x", false)]
    #[case::slash("dev/x", false)]
    #[case::dot("dev.1", false)]
    #[case::chinese("开发", false)]
    fn test_validate_branch_name_matrix(#[case] name: &str, #[case] ok: bool) {
        assert_eq!(validate_branch_name(name).is_ok(), ok);
    }
}
