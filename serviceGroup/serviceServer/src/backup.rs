//! 配置文件滚动备份 (修旧 save_file_content 单份 .backup 成功就删的窘迫)。
//!
//! 每次保存前为原文件建一份时间戳备份, 入 .config_history/<filename>/ 子目录
//! (避免污染服务根目录的文件列表), 保留最近 MAX_BACKUPS 份, 滚动删最旧。

use crate::error::Result;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const MAX_BACKUPS: usize = 3;
const HISTORY_DIR_NAME: &str = ".config_history";

/// 为 file 建一份时间戳备份, 保留最近 MAX_BACKUPS 份。
pub fn rotate_backup(file: &Path) -> Result<PathBuf> {
    let history_dir = history_dir_for(file);
    fs::create_dir_all(&history_dir)?;

    let file_name = file_name_str(file);
    let backup_name = format!("{file_name}.{}", timestamp_nanos());
    let backup_path = history_dir.join(&backup_name);
    fs::copy(file, &backup_path)?;

    prune_old(&history_dir, file_name, MAX_BACKUPS)?;
    Ok(backup_path)
}

/// 列出 file 的全部备份, 按时间倒序 (最新在前), 供 UI 展示。
pub fn list_backups(file: &Path) -> Result<Vec<PathBuf>> {
    let history_dir = history_dir_for(file);
    if !history_dir.exists() {
        return Ok(Vec::new());
    }
    let file_name = file_name_str(file);
    let prefix = format!("{}.", file_name);
    let mut backups: Vec<PathBuf> = fs::read_dir(&history_dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with(&prefix))
                .unwrap_or(false)
        })
        .collect();
    // 降序: 时间戳大 (新) 的在前。timestamp_nanos 定长 20 位, 字典序 = 时间序。
    backups.sort_by(|a, b| file_name_str(a).cmp(file_name_str(b)).reverse());
    Ok(backups)
}

fn prune_old(history_dir: &Path, file_name: &str, max: usize) -> Result<()> {
    let prefix = format!("{}.", file_name);
    let mut backups: Vec<PathBuf> = fs::read_dir(history_dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.starts_with(&prefix))
                .unwrap_or(false)
        })
        .collect();
    backups.sort_by(|a, b| file_name_str(a).cmp(file_name_str(b)).reverse());
    for old in backups.iter().skip(max) {
        let _ = fs::remove_file(old);
    }
    Ok(())
}

fn history_dir_for(file: &Path) -> PathBuf {
    let parent = file.parent().unwrap_or_else(|| Path::new("."));
    let file_name = file.file_name().unwrap_or_default();
    parent.join(HISTORY_DIR_NAME).join(file_name)
}

fn file_name_str(p: &Path) -> &str {
    p.file_name().and_then(|n| n.to_str()).unwrap_or("")
}

/// unix epoch 纳秒, 零填充 20 位 (定长, 保证字典序 = 时间序)。
fn timestamp_nanos() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("{nanos:020}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use std::fs;
    use std::thread;
    use std::time::Duration;
    use tempfile::tempdir;

    fn write_original(dir: &Path, content: &str) -> PathBuf {
        let f = dir.join("config.ini");
        fs::write(&f, content).unwrap();
        f
    }

    /// 4 次滚动备份后, 仅保留最近 3 份 (max3 滚动删最旧)。
    #[rstest]
    fn test_rotate_keeps_max_three() {
        let dir = tempdir().unwrap();
        let f = write_original(dir.path(), "v0");

        // 4 次备份, 每次间睡 2ms 保证纳秒时间戳唯一
        for i in 1..=4 {
            thread::sleep(Duration::from_millis(2));
            fs::write(&f, format!("v{i}")).unwrap();
            rotate_backup(&f).unwrap();
        }

        let backups = list_backups(&f).unwrap();
        assert_eq!(backups.len(), 3, "必须滚动保留最近 3 份");
    }

    /// 备份落在 .config_history/<filename>/ 子目录, 不污染服务根。
    #[rstest]
    fn test_backup_lives_in_history_subdir() {
        let dir = tempdir().unwrap();
        let f = write_original(dir.path(), "v0");
        rotate_backup(&f).unwrap();

        let history = dir.path().join(".config_history").join("config.ini");
        assert!(history.exists(), "备份应在 .config_history/<filename>/");
        assert_eq!(fs::read_dir(&history).unwrap().count(), 1);
    }

    /// 无备份历史时 list 返回空。
    #[rstest]
    fn test_list_backups_empty_when_none() {
        let dir = tempdir().unwrap();
        let f = write_original(dir.path(), "v0");
        assert!(list_backups(&f).unwrap().is_empty());
    }

    /// list 倒序: 最新在前。
    #[rstest]
    fn test_list_backups_newest_first() {
        let dir = tempdir().unwrap();
        let f = write_original(dir.path(), "v0");
        thread::sleep(Duration::from_millis(2));
        rotate_backup(&f).unwrap();
        thread::sleep(Duration::from_millis(2));
        rotate_backup(&f).unwrap();

        let backups = list_backups(&f).unwrap();
        assert_eq!(backups.len(), 2);
        // 第二次 (后建) 时间戳更大, 应排在前
        let first_name = file_name_str(&backups[0]);
        let second_name = file_name_str(&backups[1]);
        assert!(first_name > second_name, "最新 (时间戳大) 应在前");
    }
}
