//! Git 工具: 仓库初始化、提交、历史查询、版本内容读取。
//! 从 RoleManager 复制，WebReader 独立服务保持同一套 git 行为。

use serde_json::{json, Value};
use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// 确保工作区目录已初始化 git 仓库 (含 user 配置)。
pub fn ensure_git_initialized(role: &Path) {
    let git_dir = role.join(".git");
    if !git_dir.exists() {
        let _ = fs::create_dir_all(role);
        let _ = Command::new("git").args(["init"]).current_dir(role).output();
        let _ = Command::new("git")
            .args(["config", "user.email", "role@system"])
            .current_dir(role)
            .output();
        let _ = Command::new("git")
            .args(["config", "user.name", "role System"])
            .current_dir(role)
            .output();
    }
}

/// Git 单命令最长等待时间。超时强 kill 子进程。
const GIT_TIMEOUT: Duration = Duration::from_secs(30);
const STALE_LOCK_AGE: Duration = Duration::from_secs(10);

fn cleanup_stale_lock(role: &Path) {
    let lock = role.join(".git").join("index.lock");
    let Ok(meta) = std::fs::metadata(&lock) else { return; };
    let Ok(mtime) = meta.modified() else { return; };
    let age = mtime.elapsed().unwrap_or(Duration::ZERO);
    if age > STALE_LOCK_AGE {
        match std::fs::remove_file(&lock) {
            Ok(()) => eprintln!(
                "[webreader] removed stale index.lock at {} (age {:?})",
                lock.display(),
                age
            ),
            Err(e) => eprintln!(
                "[webreader] failed to remove stale index.lock at {}: {}",
                lock.display(),
                e
            ),
        }
    }
}

fn run_git(args: &[&str], cwd: &Path, envs: &[(&str, &str)]) -> bool {
    let mut cmd = Command::new("git");
    cmd.args(args).current_dir(cwd);
    cmd.stdout(Stdio::null()).stderr(Stdio::null());
    for (k, v) in envs {
        cmd.env(k, v);
    }
    let Ok(mut child) = cmd.spawn() else {
        eprintln!("[webreader] failed to spawn git {:?}", args);
        return false;
    };
    let deadline = Instant::now() + GIT_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return status.success(),
            Ok(None) => {
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    eprintln!(
                        "[webreader] git {:?} in {} timed out after {:?}, killed",
                        args,
                        cwd.display(),
                        GIT_TIMEOUT
                    );
                    return false;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(e) => {
                eprintln!("[webreader] git {:?} wait error: {}", args, e);
                return false;
            }
        }
    }
}

/// 提交指定文件。is_delete=true 时 add -A。
pub fn git_commit(role: &Path, file_path: &str, message: &str, is_delete: bool) -> bool {
    ensure_git_initialized(role);
    cleanup_stale_lock(role);
    let add_ok = if is_delete {
        run_git(&["add", "-A"], role, &[])
    } else {
        run_git(&["add", file_path], role, &[])
    };
    if !add_ok {
        eprintln!(
            "[webreader] git add failed in {} (file={}, is_delete={})",
            role.display(),
            file_path,
            is_delete
        );
    }
    run_git(&["commit", "-m", message], role, &[("LANG", "en_US.UTF-8")])
}

/// 文件是否有未提交改动 (工作区 vs index/HEAD)。含未跟踪新文件。
pub fn file_is_dirty(role: &Path, rel: &str) -> bool {
    ensure_git_initialized(role);
    let output = Command::new("git")
        .args(["status", "--porcelain", "--", rel])
        .current_dir(role)
        .output();
    match output {
        Ok(o) => !o.stdout.is_empty(),
        Err(_) => false,
    }
}

/// 文件最近 20 条提交历史。
pub fn file_history(role: &Path, rel: &str) -> Vec<Value> {
    let output = Command::new("git")
        .args(["log", "-20", "--format=%H|%h|%ai|%an|%s", "--", rel])
        .current_dir(role)
        .output();
    let Ok(o) = output else { return vec![]; };
    if !o.status.success() {
        return vec![];
    }
    let stdout = String::from_utf8_lossy(&o.stdout);
    stdout
        .lines()
        .filter(|l| !l.is_empty())
        .filter_map(|line| {
            let parts: Vec<&str> = line.splitn(5, '|').collect();
            if parts.len() >= 5 {
                Some(json!({
                    "hash": parts[0],
                    "short": parts[1],
                    "date": parts[2],
                    "author": parts[3],
                    "message": parts[4],
                }))
            } else {
                None
            }
        })
        .collect()
}

/// 读取文件在指定 commit 的内容。
pub fn file_version(role: &Path, rel: &str, hash: &str) -> Option<String> {
    ensure_git_initialized(role);
    let output = Command::new("git")
        .args(["show", &format!("{}:{}", hash, rel)])
        .current_dir(role)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).to_string())
}
