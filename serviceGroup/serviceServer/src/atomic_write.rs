//! 原子写 (修旧 save_file_content open('w') 截断后写失败清空 bug)。
//!
//! 流程: 编码到内存 -> 写同目录临时文件 -> os.rename 原子替换。
//! 任意步骤失败, 原文件字节零变更 (临时文件被清理, 原文件从未被截断打开)。

use crate::error::{AppError, Result};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// 原子写字节到 file。失败时原文件不动, 临时文件清理。
pub fn atomic_write_bytes(file: &Path, bytes: &[u8]) -> Result<()> {
    let tmp = tmp_path(file);
    // 1. 先把全部字节写入临时文件 (原文件此刻未被触碰)。
    if let Err(e) = fs::write(&tmp, bytes) {
        return Err(AppError::Io(e));
    }
    // 2. 同目录 rename = 原子替换 (Windows MoveFileEx REPLACE_EXISTING)。
    match fs::rename(&tmp, file) {
        Ok(()) => Ok(()),
        Err(e) => {
            // rename 失败: 清理临时文件, 原文件仍零变更。
            let _ = fs::remove_file(&tmp);
            Err(AppError::Io(e))
        }
    }
}

/// 原位截断写 (等价 legacy `open('w').write()` 的单次 WriteFile)。
///
/// **何时用此函数而非 `atomic_write_bytes`**: 目标文件被下游
/// `ReadDirectoryChangesW` 监视, 且消费者只认 `FILE_ACTION_MODIFIED` 时。
/// 典型 = zgdb assist (`CConfigManager`) 配置同步中心: 启动时
/// `dwNotifyFilter = FILTER_LAST_WRITE_NAME`, 回调 `DealConfigChange` 仅在
/// `ACTION_MODIFIED` 分支 reload + ZMQ publish; `ACTION_RENAMED_OLD/NEW` 仅
/// 打日志 (见 ConfigManagerModule.cpp)。
///
/// `atomic_write_bytes` 走 tmp + rename (MoveFileEx REPLACE_EXISTING), 在
/// `FILE_NOTIFY_CHANGE_LAST_WRITE` 下对目标文件只产生 RENAMED_OLD/NEW 事件,
/// **不产生 MODIFIED**, 导致 assistB 漏掉变更 → 跨服同步失效 (zgda/zgdf 收不到
/// 配置更新)。此函数走 `fs::write` 截断直写, 单次 WriteFile 可靠触发 MODIFIED。
///
/// **代价**: 写中途失败 (进程崩溃/磁盘满) 留半文件, 无原子回滚。调用方须先
/// `rotate_backup` 滚动备份兜底; 配置文件均为 ini/json/lua, 半文件可从
/// `.config_history/` 恢复, 且 assistB 对空串/解析失败有跳过 + 告警防御。
pub fn write_in_place_bytes(file: &Path, bytes: &[u8]) -> Result<()> {
    fs::write(file, bytes).map_err(AppError::Io)
}

fn tmp_path(file: &Path) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let pid = std::process::id();
    let name = file
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("tmp");
    let tmp_name = format!("{name}.{pid}.{nanos}.tmp");
    file.with_file_name(tmp_name)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use std::fs;
    use tempfile::tempdir;

    /// 成功写入: 内容正确, 无临时文件残留。
    #[rstest]
    fn test_atomic_write_creates_file_no_tmp_leftover() {
        let dir = tempdir().unwrap();
        let f = dir.path().join("cfg.ini");

        atomic_write_bytes(&f, b"hello").unwrap();

        assert_eq!(fs::read(&f).unwrap(), b"hello");
        let tmps: Vec<_> = fs::read_dir(dir.path())
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.ends_with(".tmp"))
            .collect();
        assert!(tmps.is_empty(), "成功后不应残留 .tmp 文件");
    }

    /// 覆盖既有文件: 新内容完整替换旧内容。
    #[rstest]
    fn test_atomic_write_overwrites_existing() {
        let dir = tempdir().unwrap();
        let f = dir.path().join("cfg.ini");
        fs::write(&f, b"old").unwrap();

        atomic_write_bytes(&f, b"new content").unwrap();

        assert_eq!(fs::read(&f).unwrap(), b"new content");
    }

    /// 写入不存在父目录: 返回错误, 不 panic, 不留 tmp。
    #[rstest]
    fn test_atomic_write_missing_parent_returns_error() {
        let dir = tempdir().unwrap();
        let f = dir.path().join("no_such_dir").join("cfg.ini");

        let err = atomic_write_bytes(&f, b"x");
        assert!(err.is_err(), "父目录缺失应返错误");
    }

    /// 原位写覆盖既有文件: 新内容完整替换, 无 tmp 残留。
    #[rstest]
    fn test_write_in_place_overwrites_existing() {
        let dir = tempdir().unwrap();
        let f = dir.path().join("cfg.ini");
        fs::write(&f, b"old").unwrap();

        write_in_place_bytes(&f, b"new content").unwrap();

        assert_eq!(fs::read(&f).unwrap(), b"new content");
        let tmps: Vec<_> = fs::read_dir(dir.path())
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.ends_with(".tmp"))
            .collect();
        assert!(tmps.is_empty(), "原位写不应产生 tmp 文件");
    }
}
