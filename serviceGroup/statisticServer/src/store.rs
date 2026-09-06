//! SQLite 存储：requests 表 schema 创建、旧列自动迁移、请求落库。
//!
//! 对齐线上 `proxy_server.py::init_db` 语义：
//! - requests 表含 cost 列（峰谷计价落库即算好）
//! - meta 表存 pricing_version，变化时重算所有历史 cost

use rusqlite::{Connection, OptionalExtension};
use std::path::Path;

use crate::model::{calc_charges, Usage, PRICING_VERSION};

/// 一条请求记录（cost/credits 由落库时按请求时刻与模型分派计算）。
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
    /// API 来源名（F1 来源分类；旧行/未知为 "unknown"）。
    pub source: String,
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
            tool_calls INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ok',
            format TEXT DEFAULT 'anthropic',
            cost REAL DEFAULT 0,
            credits REAL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ts ON requests(ts);
        CREATE INDEX IF NOT EXISTS idx_session ON requests(session_id);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        ",
    )?;
    // API 来源表（多上游切换）
    crate::sources::init_schema(&conn)?;
    // 旧列缺失自动迁移
    migrate_add_column(&conn, "cache_miss_tokens", "INTEGER DEFAULT 0")?;
    migrate_add_column(&conn, "format", "TEXT DEFAULT 'anthropic'")?;
    migrate_add_column(&conn, "cost", "REAL DEFAULT 0")?;
    migrate_add_column(&conn, "credits", "REAL DEFAULT 0")?;
    migrate_add_column(&conn, "source", "TEXT DEFAULT 'unknown'")?;
    migrate_add_column(&conn, "tool_calls", "INTEGER DEFAULT 0")?;
    // cost 回填：旧行补算
    backfill_cost(&conn)?;
    // credits 回填：旧行按公式补算（超算平台表，无峰谷）
    backfill_credits(&conn)?;
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
        let (c, _) = calc_charges(&model, prompt, hit, out, 0, Some(&ts));
        if c > 0.0 {
            conn.execute("UPDATE requests SET cost=?1 WHERE id=?2", rusqlite::params![c, rid])?;
        }
    }
    Ok(())
}

/// 回填 credits：旧行按超算平台表补算（无峰谷）。
fn backfill_credits(conn: &Connection) -> rusqlite::Result<()> {
    let rows: Vec<(String, String, i64, i64, i64, i64)> = {
        let mut stmt = conn.prepare(
            "SELECT id, model, prompt_tokens, cache_hit_tokens, completion_tokens, tool_calls
             FROM requests WHERE (credits IS NULL OR credits = 0) AND (prompt_tokens > 0 OR completion_tokens > 0 OR tool_calls > 0)",
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
    for (rid, model, prompt, hit, out, tools) in rows {
        let (_, c) = calc_charges(&model, prompt, hit, out, tools, None);
        if c > 0.0 {
            conn.execute("UPDATE requests SET credits=?1 WHERE id=?2", rusqlite::params![c, rid])?;
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
            let (c, _) = calc_charges(&model, prompt, hit, out, 0, Some(&ts));
            conn.execute("UPDATE requests SET cost=?1 WHERE id=?2", rusqlite::params![c, rid])?;
        }
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('pricing_version',?1)",
            rusqlite::params![PRICING_VERSION],
        )?;
    }
    Ok(())
}

/// 落库一条请求（INSERT OR REPLACE），cost/credits 按模型分派计算
/// （glm → coding plan 积分；其余 → 超算 cost+credits）。
pub fn record(conn: &Connection, r: &RequestRecord) -> rusqlite::Result<()> {
    let (cost, credits) = calc_charges(
        &r.model,
        r.usage.prompt_tokens,
        r.usage.cache_hit_tokens,
        r.usage.completion_tokens,
        r.usage.tool_calls,
        Some(&r.ts),
    );
    conn.execute(
        "INSERT OR REPLACE INTO requests
         (id, ts, session_id, model, prompt_tokens, completion_tokens,
          total_tokens, cache_hit_tokens, cache_miss_tokens, tool_calls, latency_ms, status, format, cost, credits, source)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16)",
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
            r.usage.tool_calls,
            r.latency_ms,
            r.status,
            r.format,
            cost,
            credits,
            r.source,
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
        let has_source: bool = conn
            .prepare("SELECT 1 FROM pragma_table_info('requests') WHERE name='source'")
            .unwrap()
            .exists([])
            .unwrap();
        assert!(has_source, "source should be migrated in");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn insert_record_with_cost() {
        let conn = tmp_db();
        let r = RequestRecord {
            id: "req_test".into(),
            ts: "2026-08-20T10:00:00".into(), // 周四 10:00 高峰（基准价）
            session_id: "sess1".into(),
            model: "deepseek-v4-flash".into(),
            usage: Usage { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15, cache_hit_tokens: 3, cache_miss_tokens: 7, tool_calls: 0 },
            latency_ms: 100,
            status: "ok".into(),
            format: "anthropic".into(),
            source: "ds-main".into(),
        };
        record(&conn, &r).unwrap();
        let n: i64 = conn
            .query_row("SELECT COUNT(*) FROM requests", [], |row| row.get(0))
            .unwrap();
        assert_eq!(n, 1);
        let cost: f64 = conn
            .query_row("SELECT cost FROM requests WHERE id='req_test'", [], |row| row.get(0))
            .unwrap();
        let expect = (7.0 * 0.44 + 3.0 * 0.014 + 5.0 * 1.32) / 1_000_000.0;
        assert!((cost - expect).abs() < 1e-12, "cost={cost} expect={expect}");
    }

    #[test]
    fn record_persists_source() {
        let conn = tmp_db();
        let r = RequestRecord {
            id: "req_src".into(),
            ts: "2026-08-20T10:00:00".into(),
            session_id: "s".into(),
            model: "deepseek-v4-flash".into(),
            usage: Usage::default(),
            latency_ms: 10,
            status: "ok".into(),
            format: "anthropic".into(),
            source: "glm-team".into(),
        };
        record(&conn, &r).unwrap();
        let src: String = conn
            .query_row("SELECT source FROM requests WHERE id='req_src'", [], |row| row.get(0))
            .unwrap();
        assert_eq!(src, "glm-team");
    }

    #[test]
    fn record_glm_zero_cost_positive_credits() {
        let conn = tmp_db();
        let r = RequestRecord {
            id: "req_glm".into(),
            ts: "2026-08-20T15:00:00".into(), // GLM 高峰
            session_id: "s".into(),
            model: "glm-5.3".into(),
            usage: Usage { prompt_tokens: 10_000, completion_tokens: 2_000, total_tokens: 12_000, cache_hit_tokens: 1_000, cache_miss_tokens: 9_000, tool_calls: 2 },
            latency_ms: 10,
            status: "ok".into(),
            format: "anthropic".into(),
            source: "glm-team".into(),
        };
        record(&conn, &r).unwrap();
        let (cost, credits, tools): (f64, f64, i64) = conn
            .query_row("SELECT cost, credits, tool_calls FROM requests WHERE id='req_glm'", [], |row| {
                Ok((row.get(0)?, row.get(1)?, row.get(2)?))
            })
            .unwrap();
        assert_eq!(cost, 0.0, "GLM 不计按量 cost");
        assert_eq!(tools, 2, "tool_calls 落库");
        let expect = (9000.0 * 6.9 + 1000.0 * 1.7 + 2000.0 * 24.0) / 10_000.0 + 2.0 * 1.2;
        assert!((credits - expect).abs() < 1e-9, "credits={credits} expect={expect}");
    }
}
