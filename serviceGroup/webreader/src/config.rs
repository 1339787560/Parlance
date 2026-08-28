//! WebReader standalone 配置。
//!
//! config.json 支持:
//! - port            : 监听端口 (默认 5090)
//! - workspace       : 展示/读写的工作区根目录 (必填)
//! - static_dir      : 前端静态文件目录 (相对 config.json 或绝对路径, 默认 "static")
//! - visible_roots   : root 层可见目录白名单; 缺省/空 = 全显
//! - hidden_folders  : 隐藏的文件夹名
//! - hidden_files    : 隐藏的文件名
//! - hidden_patterns : 隐藏正则 (匹配相对路径或条目名, 命中即隐藏)
//! - visible_dot_dirs: 例外显示的 dotfile 目录 (默认 [".claude"])
//! - search_max_file_kb: 搜索内容索引跳过的大文件阈值 (默认 1024, 单位 KB)

use regex::Regex;
use serde::Deserialize;
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

static CONFIG: OnceLock<Config> = OnceLock::new();

#[derive(Deserialize)]
struct RawConfig {
    port: Option<u16>,
    workspace: String,
    static_dir: Option<String>,
    visible_roots: Option<Vec<String>>,
    hidden_folders: Option<Vec<String>>,
    hidden_files: Option<Vec<String>>,
    hidden_patterns: Option<Vec<String>>,
    visible_dot_dirs: Option<Vec<String>>,
    search_max_file_kb: Option<u64>,
}

pub struct Config {
    pub port: u16,
    pub workspace: PathBuf,
    pub static_dir: PathBuf,
    pub visible_roots: Option<HashSet<String>>,
    pub hidden_folders: HashSet<String>,
    pub hidden_files: HashSet<String>,
    pub hidden_patterns: Vec<Regex>,
    pub visible_dot_dirs: HashSet<String>,
    pub search_max_file_kb: u64,
}

fn to_set(v: Option<Vec<String>>) -> HashSet<String> {
    v.unwrap_or_default().into_iter().collect()
}

fn resolve_path(base: &Path, p: &str) -> PathBuf {
    let path = PathBuf::from(p);
    if path.is_absolute() {
        path
    } else {
        base.join(path)
    }
}

pub fn init(config_path: &Path) -> Result<(), String> {
    let text = std::fs::read_to_string(config_path)
        .map_err(|e| format!("read config {} failed: {}", config_path.display(), e))?;
    let raw: RawConfig = serde_json::from_str(&text)
        .map_err(|e| format!("parse config {} failed: {}", config_path.display(), e))?;
    let base = config_path.parent().unwrap_or_else(|| Path::new("."));

    let hidden_patterns = raw
        .hidden_patterns
        .unwrap_or_default()
        .into_iter()
        .map(|s| Regex::new(&s).map_err(|e| format!("invalid hidden_pattern {:?}: {}", s, e)))
        .collect::<Result<Vec<_>, _>>()?;

    let cfg = Config {
        port: raw.port.unwrap_or(5090),
        workspace: resolve_path(base, &raw.workspace),
        static_dir: resolve_path(base, raw.static_dir.as_deref().unwrap_or("static")),
        visible_roots: {
            let set = to_set(raw.visible_roots);
            if set.is_empty() { None } else { Some(set) }
        },
        hidden_folders: {
            let mut set = to_set(raw.hidden_folders);
            if set.is_empty() {
                set.extend(
                    [
                        ".git", "target", "node_modules", "RoleManager", "WebReader", "tools", "venv",
                    ]
                    .map(String::from),
                );
            }
            set
        },
        hidden_files: {
            let mut set = to_set(raw.hidden_files);
            if set.is_empty() {
                set.insert("RoleManager.exe".to_string());
            }
            set
        },
        hidden_patterns,
        visible_dot_dirs: {
            let mut set = to_set(raw.visible_dot_dirs);
            if set.is_empty() {
                set.insert(".claude".to_string());
            }
            set
        },
        search_max_file_kb: raw.search_max_file_kb.unwrap_or(1024),
    };

    if !cfg.workspace.exists() {
        return Err(format!("workspace not found: {}", cfg.workspace.display()));
    }
    if !cfg.static_dir.exists() {
        return Err(format!("static_dir not found: {}", cfg.static_dir.display()));
    }

    let _ = CONFIG.set(cfg);
    Ok(())
}

pub fn config() -> &'static Config {
    CONFIG.get().expect("webreader config not initialized")
}
