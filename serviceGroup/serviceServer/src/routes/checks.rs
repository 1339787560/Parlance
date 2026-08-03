//! 配置文件操作前置校验 (路径越权 + 扩展名白名单), 供 config_file 与 branches 复用。

use crate::error::{AppError, Result};
use crate::path_check::is_within_any;
use crate::state::AppState;
use std::path::Path;

const ALLOWED_EXTS: &[&str] = &["ini", "json", "lua"];

pub fn assert_within_roots(state: &AppState, target: &Path) -> Result<()> {
    let roots = state.path_map.valid_roots();
    if is_within_any(target, &roots) {
        Ok(())
    } else {
        Err(AppError::Forbidden)
    }
}

pub fn assert_allowed_ext(path: &Path) -> Result<()> {
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
