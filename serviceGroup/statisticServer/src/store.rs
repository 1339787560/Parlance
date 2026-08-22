//! SQLite 存储：requests 表 schema 创建、旧列自动迁移、请求落库。
//!
//! 对齐线上 `proxy_server.py::init_db` 语义：
//! - requests 表含 cost 列（峰谷计价落库即算好）
//! - meta 表存 pricing_version，变化时重算所有历史 cost

use rusqlite::{Connection, OptionalExtension};
use std::path::Path;

use crate::model::{calc_cost, Usage, PRICING_VERSION};

/// 一条请求记录（cost 由落库时按请求时刻计算）。
#[derive(Debug, Clone)]
pub struct RequestRecord {
    pub id: String,
    pub ts: String,
    pub session_id: String,
    pub model: String,
    pub usage: Usage,
    pub latency_ms: i64,
    pub status: String,
    pub format: String,
}

/// 打开（或创建）SQLite 数据库并初始化 schema。
///
/// 对齐线上 init_db：建表 + 索引 + 旧列缺失自动迁移 + cost 回填 + 定价版本迁移。
pub fn init_db(path: &Path) -> rusqlite::Result<Connection> {
    let conn = Connection::open(path)?;
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS requests (
            id TEXT PRIMARY KEY,
            ts TEXT, session_id TEXT, model TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cache_hit_tokens INTEGER DEFAULT 0,
            cache_miss_tokens INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ok',
            format TEXT DEFAULT 'anthropic'
        );
        CREATE INDEX IF NOT EXISTS idx_ts ON requests(ts);
        CREATE INDEX IF NOT EXISTS idx_session ON requests(session_id);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        ",
    )?;
    // 旧列缺失自动迁移
    migrate_add_column(&conn, "cache_miss_tokens", "INTEGER DEFAULT 0")?;
    migrate_add_column(&conn, "format", "TEXT DEFAULT 'anthropic'")?;
    migrate_add_column(&conn, "cost", "REAL DEFAULT 0")?;
    // cost 回填：旧行补算
    backfill_cost(&conn)?;
    // 定价版本迁移：变化时按当前价格表重算所有历史 cost
    migrate_pricing_version(&conn)?;
    Ok(conn)
}

/// 若列缺失则 ALTER TABLE 补列。
fn migrate_add_column(conn: &Connection, column: &str, decl: &str) -> rusqlite::Result<()> {
    let has: bool = conn
        .prepare("SELECT 1 FROM pragma_table_info('requests') WHERE name=?1")?
        .exists([column])?;
    if !has {
        conn.execute_batch(&format!(
            "ALTER TABLE requests ADD COLUMN {column} {decl};"
        ))?;
    }
    Ok(())
}

/// 回填：旧行按公式补算 cost（ts 视为北京时间）。
fn backfill_cost(conn: &Connection) -> rusqlite::Result<()> {
    let rows: Vec<(String, String, String, i64, i64, i64)> = {
        let mut stmt = conn.prepare(
            "SELECT id, ts, model, prompt_tokens, cache_hit_tokens, completion_tokens
             FROM requests WHERE (cost IS NULL OR cost = 0) AND (prompt_tokens > 0 OR completion_tokens > 0)",
        )?;
        let mut out = Vec::new();
        let mut it = stmt.query([])?;
        while let Some(r) = it.next()? {
            out.push((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                r.get(4)?,
                r.get(5)?,
            ));
        }
        out
    };
    for (rid, ts, model, prompt, hit, out) in rows {
        let c = calc_cost(&model, prompt, hit, out, Some(&ts));
        if c > 0.0 {
            conn.execute("UPDATE requests SET cost=?1 WHERE id=?2", rusqlite::params![c, rid])?;
        }
    }
    Ok(())
}

/// 定价版本迁移：PRICING_VERSION 变化时重算所有历史 cost。
fn migrate_pricing_version(conn: &Connection) -> rusqlite::Result<()> {
    let ver: Option<String> = conn
        .query_row("SELECT value FROM meta WHERE key='pricing_version'", [], |r| r.get(0))
        .optional()?;
    if ver.as_deref() != Some(PRICING_VERSION) {
        let rows: Vec<(String, String, String, i64, i64, i64)> = {
            let mut stmt = conn.prepare(
                "SELECT id, ts, model, prompt_tokens, cache_hit_tokens, completion_tokens
                 FROM requests WHERE (prompt_tokens > 0 OR completion_tokens > 0)",
            )?;
            let mut out = Vec::new();
            let mut it = stmt.query([])?;
            while let Some(r) = it.next()? {
                out.push((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                    r.get(5)?,
                ));
            }
            out
        };
        for (rid, ts, model, prompt, hit, out) in rows {
            let c = calc_cost(&model, prompt, hit, out, Some(&ts));
            conn.execute("UPDATE requests SET cost=?1 WHERE id=?2", rusqlite::params![c, rid])?;
        }
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('pricing_version',?1)",
            rusqlite::params![PRICING_VERSION],
        )?;
    }
    Ok(())
}

/// 落库一条请求（INSERT OR REPLACE），cost 按请求时刻算好。
pub fn record(conn: &Connection, r: &RequestRecord) -> rusqlite::Result<()> {
    let cost = calc_cost(
        &r.model,
        r.usage.prompt_tokens,
        r.usage.cache_hit_tokens,
        r.usage.completion_tokens,
        Some(&r.ts),
    );
    conn.execute(
        "INSERT OR REPLACE INTO requests
         (id, ts, session_id, model, prompt_tokens, completion_tokens,
          total_tokens, cache_hit_tokens, cache_miss_tokens, latency_ms, status, format, cost)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
        rusqlite::params![
            r.id,
            r.ts,
            r.session_id,
            r.model,
            r.usage.prompt_tokens,
            r.usage.completion_tokens,
            r.usage.total_tokens,
            r.usage.cache_hit_tokens,
            r.usage.cache_miss_tokens,
            r.latency_ms,
            r.status,
            r.format,
            cost,
        ],
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp_db() -> Connection {
        init_db(Path::new(":memory:")).expect("init_db")
    }

    #[test]
    fn create_schema_with_cost_and_meta() {
        let conn = tmp_db();
        let has_cost: bool = conn
            .prepare("SELECT 1 FROM pragma_table_info('requests') WHERE name='cost'")
            .unwrap()
            .exists([])
            .unwrap();
        assert!(has_cost, "cost column should exist");
        let has_meta: bool = conn
            .prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'")
            .unwrap()
            .exists([])
            .unwrap();
        assert!(has_meta, "meta table should exist");
    }

    #[test]
    fn migrate_old_schema() {
        let dir = std::env::temp_dir();
        let path = dir.join(format!("ds_stats_old_{}.db", uuid::Uuid::new_v4()));
        {
            let conn = Connection::open(&path).unwrap();
            conn.execute_batch(
                "CREATE TABLE requests (
                    id TEXT PRIMARY KEY, ts TEXT, session_id TEXT, model TEXT,
                    prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0, cache_hit_tokens INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0, status TEXT DEFAULT 'ok'
                );",
            )
            .unwrap();
        }
        let conn = init_db(&path).unwrap();
        let has_cost: bool = conn
            .prepare("SELECT 1 FROM pragma_table_info('requests') WHERE name='cost'")
            .unwrap()
            .exists([])
            .unwrap();
        assert!(has_cost, "cost should be migrated in");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn insert_record_with_cost() {
        let conn = tmp_db();
        let r = RequestRecord {
            id: "req_test".into(),
            ts: "2026-08-20T00:00:00".into(),
            session_id: "sess1".into(),
            model: "deepseek-v4-flash".into(),
            usage: Usage { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15, cache_hit_tokens: 3, cache_miss_tokens: 7 },
            latency_ms: 100,
            status: "ok".into(),
            format: "anthropic".into(),
        };
        record(&conn, &r).unwrap();
        let n: i64 = conn
            .query_row("SELECT COUNT(*) FROM requests", [], |row| row.get(0))
            .unwrap();
        assert_eq!(n, 1);
        let cost: f64 = conn
            .query_row("SELECT cost FROM requests WHERE id='req_test'", [], |row| row.get(0))
            .unwrap();
        let expect = (7.0 * 1.5 + 3.0 * 0.05 + 5.0 * 4.5) / 1_000_000.0;
        assert!((cost - expect).abs() < 1e-12, "cost={cost} expect={expect}");
    }
}
