pub mod branches;
pub mod checks;
pub mod config_file;
pub mod config_files;
pub mod fetch;
pub mod recorder;
pub mod records;
pub mod services;
pub mod spideorder;
pub mod templates;

use crate::error::{AppError, Result};
use serde::Serialize;
use std::path::Path;

/// 读 config.json 整份内容 (Value 形态, 供 spideOrder/服务配置改写用)。
/// 不走 path_map 缓存 (path_map 只解析 service 段), 每次读盘保证拿到最新。
pub fn read_config_value(config_path: &Path) -> Result<serde_json::Value> {
    if !config_path.exists() {
        return Err(AppError::NotFound);
    }
    let raw = std::fs::read_to_string(config_path)?;
    Ok(serde_json::from_str(&raw)?)
}

/// 写 config.json: 滚动备份 + 原子写, 4 空格缩进 (对齐 legacy json.dump indent=4,
/// ensure_ascii=False 即 UTF-8 原样输出, serde_json 默认即 raw UTF-8)。
pub fn write_config_value(config_path: &Path, config: &serde_json::Value) -> Result<()> {
    crate::backup::rotate_backup(config_path)?;
    let mut buf = Vec::new();
    let fmt = serde_json::ser::PrettyFormatter::with_indent(b"    ");
    let mut ser = serde_json::Serializer::with_formatter(&mut buf, fmt);
    config.serialize(&mut ser)?;
    crate::atomic_write::atomic_write_bytes(config_path, &buf)
}
