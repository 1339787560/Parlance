//! 共享应用状态：SQLite 连接、SSE 广播信道、上游目标配置。

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use rusqlite::Connection;

use crate::sse::SseSender;

/// 上游目标配置（对齐旧环境变量语义）。
#[derive(Debug, Clone)]
pub struct Targets {
    pub anthropic: String,
    pub openai: String,
}

/// 共享应用状态。
pub struct AppState {
    /// SQLite 连接（Mutex 包裹，写串行化）。
    pub db: Arc<Mutex<Connection>>,
    /// SSE 广播发送端。
    pub sse: SseSender,
    /// 上游目标。
    pub targets: Targets,
    /// 静态目录（看板）。
    pub static_dir: PathBuf,
}

impl AppState {
    pub fn new(
        db: Arc<Mutex<Connection>>,
        sse: SseSender,
        targets: Targets,
        static_dir: PathBuf,
    ) -> Self {
        Self { db, sse, targets, static_dir }
    }
}
