//! API 来源管理：多套 DeepSeek 上游（name + api_key + 双 target），支持运行时切换。
//!
//! 语义对齐旧环境变量：每来源 = 一个上游提供商，含
//! - `api_key`：代理 key（客户端未提供 Authorization/x-api-key 时回退用）
//! - `anthropic`：Anthropic 格式目标 base
//! - `openai`：OpenAI 格式目标 base
//!
//! 持久化到 SQLite（`sources` 表 + `meta.active_source`），运行期改配置即时生效，
//! 无需重启；重启后从 DB 恢复。

use rusqlite::{Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;

/// 一个 API 来源（provider）。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ApiSource {
    pub name: String,
    pub api_key: String,
    pub anthropic: String,
    pub openai: String,
}

/// 来源管理器：内存态（RwLock 保护，代理每请求读激活来源）。
#[derive(Debug, Default)]
pub struct SourceManager {
    pub sources: Vec<ApiSource>,
    pub active: String,
}

impl SourceManager {
    pub fn new(sources: Vec<ApiSource>, active: String) -> Self {
        Self { sources, active }
    }

    /// 当前激活来源；未找到时回退第一个来源。
    pub fn active_source(&self) -> Option<&ApiSource> {
        self.sources
            .iter()
            .find(|s| s.name == self.active)
            .or_else(|| self.sources.first())
    }

    /// 当前激活来源的 api_key（空 = 允许客户端 key 直通）。
    pub fn active_api_key(&self) -> String {
        self.active_source().map(|s| s.api_key.clone()).unwrap_or_default()
    }

    pub fn get(&self, name: &str) -> Option<&ApiSource> {
        self.sources.iter().find(|s| s.name == name)
    }

    /// 新增来源；重名返回 Err。
    pub fn create(&mut self, src: ApiSource) -> Result<(), String> {
        if src.name.trim().is_empty() {
            return Err("名称不能为空".into());
        }
        if self.sources.iter().any(|s| s.name == src.name) {
            return Err(format!("来源 '{}' 已存在", src.name));
        }
        if self.sources.is_empty() {
            self.active = src.name.clone();
        }
        self.sources.push(src);
        Ok(())
    }

    /// 更新来源（name 为主键，不可改名）；不存在返回 Err。
    pub fn update(&mut self, name: &str, src: ApiSource) -> Result<(), String> {
        let Some(existing) = self.sources.iter_mut().find(|s| s.name == name) else {
            return Err(format!("来源 '{}' 不存在", name));
        };
        existing.api_key = src.api_key;
        existing.anthropic = src.anthropic;
        existing.openai = src.openai;
        Ok(())
    }

    /// 删除来源；删除激活来源后回退到第一个剩余来源。最后一条不可删。
    pub fn delete(&mut self, name: &str) -> Result<(), String> {
        if self.sources.len() <= 1 {
            return Err("至少保留一个 API 来源".into());
        }
        let before = self.sources.len();
        self.sources.retain(|s| s.name != name);
        if self.sources.len() == before {
            return Err(format!("来源 '{}' 不存在", name));
        }
        if self.active == name {
            self.active = self
                .sources
                .first()
                .map(|s| s.name.clone())
                .unwrap_or_default();
        }
        Ok(())
    }

    /// 切换激活来源；不存在返回 Err。
    pub fn activate(&mut self, name: &str) -> Result<(), String> {
        if self.get(name).is_none() {
            return Err(format!("来源 '{}' 不存在", name));
        }
        self.active = name.to_string();
        Ok(())
    }
}

// ---- SQLite 持久化 ----

/// 建表（幂等）。sources 持久化依赖 meta 表（存 active_source）。
pub fn init_schema(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
         CREATE TABLE IF NOT EXISTS sources (
            name TEXT PRIMARY KEY,
            api_key TEXT DEFAULT '',
            anthropic TEXT DEFAULT '',
            openai TEXT DEFAULT ''
        );",
    )?;
    Ok(())
}

/// 从 DB 载入来源列表与激活名。
pub fn load(conn: &Connection) -> rusqlite::Result<(Vec<ApiSource>, String)> {
    let mut stmt = conn
        .prepare("SELECT name, api_key, anthropic, openai FROM sources ORDER BY rowid")?;
    let sources = stmt
        .query_map([], |r| {
            Ok(ApiSource {
                name: r.get(0)?,
                api_key: r.get(1)?,
                anthropic: r.get(2)?,
                openai: r.get(3)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    let active = conn
        .query_row("SELECT value FROM meta WHERE key='active_source'", [], |r| r.get(0))
        .optional()?
        .unwrap_or_default();
    Ok((sources, active))
}

/// 全量落库（增删改后调用，事务保证一致性）。
pub fn save_all(conn: &Connection, m: &SourceManager) -> rusqlite::Result<()> {
    conn.execute("DELETE FROM sources", [])?;
    for s in &m.sources {
        conn.execute(
            "INSERT OR REPLACE INTO sources(name, api_key, anthropic, openai) VALUES (?1,?2,?3,?4)",
            rusqlite::params![s.name, s.api_key, s.anthropic, s.openai],
        )?;
    }
    conn.execute(
        "INSERT OR REPLACE INTO meta(key,value) VALUES('active_source',?1)",
        rusqlite::params![m.active],
    )?;
    Ok(())
}

/// 以 `RwLock` 包一层便于 AppState 持有；内部再按 DB 同步。
pub type SourcesHandle = Arc<RwLock<SourceManager>>;

use std::sync::Arc;

#[cfg(test)]
mod tests {
    use super::*;

    fn src(name: &str) -> ApiSource {
        ApiSource {
            name: name.into(),
            api_key: format!("sk-{name}"),
            anthropic: format!("http://{name}:82"),
            openai: format!("http://{name}:82/v1"),
        }
    }

    #[test]
    fn first_source_becomes_active() {
        let mut m = SourceManager::default();
        m.create(src("a")).unwrap();
        assert_eq!(m.active, "a");
        assert_eq!(m.active_source().unwrap().name, "a");
        assert_eq!(m.active_api_key(), "sk-a");
    }

    #[test]
    fn create_duplicate_rejected() {
        let mut m = SourceManager::default();
        m.create(src("a")).unwrap();
        assert!(m.create(src("a")).is_err());
        assert_eq!(m.sources.len(), 1);
    }

    #[test]
    fn activate_and_get() {
        let mut m = SourceManager::default();
        m.create(src("a")).unwrap();
        m.create(src("b")).unwrap();
        assert_eq!(m.active, "a"); // 首个为激活
        m.activate("b").unwrap();
        assert_eq!(m.active_api_key(), "sk-b");
        assert!(m.activate("nope").is_err());
    }

    #[test]
    fn update_keeps_name() {
        let mut m = SourceManager::default();
        m.create(src("a")).unwrap();
        let mut new = src("a");
        new.api_key = "sk-new".into();
        m.update("a", new.clone()).unwrap();
        assert_eq!(m.get("a").unwrap().api_key, "sk-new");
        // 不存在 → Err
        assert!(m.update("x", new).is_err());
    }

    #[test]
    fn delete_active_falls_back() {
        let mut m = SourceManager::default();
        m.create(src("a")).unwrap();
        m.create(src("b")).unwrap();
        m.activate("b").unwrap();
        m.delete("b").unwrap();
        assert_eq!(m.active, "a");
    }

    #[test]
    fn last_source_not_deletable() {
        let mut m = SourceManager::default();
        m.create(src("a")).unwrap();
        assert!(m.delete("a").is_err());
    }

    #[test]
    fn db_roundtrip() {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        init_schema(&conn).unwrap();
        let mut m = SourceManager::default();
        m.create(src("a")).unwrap();
        m.create(src("b")).unwrap();
        m.activate("b").unwrap();
        save_all(&conn, &m).unwrap();

        let (loaded, active) = load(&conn).unwrap();
        assert_eq!(loaded.len(), 2);
        assert_eq!(active, "b");
        assert_eq!(loaded[1].api_key, "sk-b");
    }
}
