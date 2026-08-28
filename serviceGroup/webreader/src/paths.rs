//! 路径工具: 工作区根目录 + 沙箱化相对路径解析 + roles/ 透明前缀。
//! 与 RoleManager 保持一致，保证 WebReader API 行为不变。

use std::fs;
use std::path::{Path, PathBuf};

/// 沙箱化解析相对路径: 确保请求路径不会逃逸出 base。
/// 返回规范化后的相对路径字符串 (相对 base), 拒绝穿越则返回 None。
pub fn safe_relative_path(base: &Path, path: &str) -> Option<String> {
    if path.is_empty() {
        return Some(String::new());
    }
    let stripped = path.trim_start_matches(|c| c == '/' || c == '\\');
    let full = base.join(stripped);
    let canonical_base = if base.exists() {
        base.canonicalize().unwrap_or_else(|_| base.to_path_buf())
    } else {
        base.to_path_buf()
    };
    let parent = match full.parent() {
        Some(p) => p,
        None => return Some(stripped.to_string()),
    };
    if !parent.exists() {
        let normalized = full.components().collect::<PathBuf>();
        let cn = if let Ok(c) = normalized.canonicalize() {
            c
        } else if let Ok(cp) = parent.canonicalize() {
            if cp.starts_with(&canonical_base) || canonical_base.starts_with(&cp) {
                return Some(stripped.to_string());
            }
            return Some(stripped.to_string());
        } else {
            return Some(stripped.to_string());
        };
        if cn.starts_with(&canonical_base) || canonical_base.starts_with(&cn) {
            return Some(stripped.to_string());
        }
        return None;
    }
    match parent.canonicalize() {
        Ok(canonical_full) => {
            if canonical_full.starts_with(&canonical_base) {
                Some(stripped.to_string())
            } else {
                None
            }
        }
        Err(_) => Some(stripped.to_string()),
    }
}

const SKIP_DIRS: &[&str] = &[".git", "QuickStartForRole", "WorkFlow", "projCommon", "shared"];

/// 扫描 workspace/roles/ 下含 L0_Index.md 的子目录作为角色列表。
pub fn discover_roles(root: &Path) -> Vec<String> {
    let mut roles: Vec<String> = Vec::new();
    let roles_dir = root.join("roles");
    let Ok(entries) = fs::read_dir(&roles_dir) else {
        eprintln!("[webreader] roles/ 目录不存在或不可读: {}", roles_dir.display());
        return roles;
    };
    for e in entries.flatten() {
        let name = e.file_name().to_string_lossy().to_string();
        if SKIP_DIRS.contains(&name.as_str()) || name == ".git" {
            continue;
        }
        let is_global = name == "global";
        if e.path().is_dir() && (is_global || e.path().join("L0_Index.md").exists()) {
            roles.push(name);
        }
    }
    roles.sort();
    roles
}

/// 透明前缀：path 首段若为已知角色名 → 补 "roles/" 前缀；否则原样返回。
pub fn apply_role_prefix(path: &str, roles: &[String]) -> String {
    if path.is_empty() {
        return String::new();
    }
    if path.starts_with("roles/") || path.starts_with("roles\\") {
        return path.to_string();
    }
    let first_seg = path
        .split(|c| c == '/' || c == '\\')
        .next()
        .unwrap_or("");
    if !first_seg.is_empty() && roles.iter().any(|r| r == first_seg) {
        format!("roles/{}", path)
    } else {
        path.to_string()
    }
}
