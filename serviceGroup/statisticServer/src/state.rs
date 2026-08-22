//! 共享应用状态：SQLite 连接、SSE 广播信道、API 来源管理。

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use rusqlite::Connection;

use crate::sse::SseSender;
use crate::sources::SourcesHandle;

/// 共享应用状态。
pub struct AppState {
    /// SQLite 连接（Mutex 包裹，写串行化）。
    pub db: Arc<Mutex<Connection>>,
    /// SSE 广播发送端。
    pub sse: SseSender,
    /// API 来源管理（RwLock，代理每请求读激活来源）。
    pub sources: SourcesHandle,
    /// 静态目录（看板）。
    pub static_dir: PathBuf,
}

impl AppState {
    pub fn new(
        db: Arc<Mutex<Connection>>,
        sse: SseSender,
        sources: SourcesHandle,
        static_dir: PathBuf,
    ) -> Self {
        Self { db, sse, sources, static_dir }
    }
}
