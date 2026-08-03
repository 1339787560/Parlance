//! 模板存储 (SQLite, 对齐 legacy CustomRoute/TemplateDB.py)。
//!
//! 表 templates(id, name, type, data TEXT(json))。存 deposit 页用的充值模板。
//! DB 路径由 AppState 注入 (默认 legacy_dir/CustomRoute/templates.db 复用旧库)。

use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::sync::Mutex;

use crate::error::{AppError, Result};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Template {
    pub id: i64,
    pub name: String,
    #[serde(rename = "type")]
    pub svc_type: String,
    pub data: serde_json::Value,
}

/// 模板存储: 持 SQLite 连接 (Mutex 串行化写, 对齐 legacy 单连接模型)。
pub struct TemplateStore {
    conn: Mutex<Connection>,
}

impl TemplateStore {
    /// 打开 (不存在自动建表)。
    pub fn open(db_path: &Path) -> Result<Self> {
        let conn = Connection::open(db_path).map_err(map_err)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL
            )",
        )
        .map_err(map_err)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    /// 插入模板, 返 id。
    pub fn add(&self, name: &str, svc_type: &str, data: &serde_json::Value) -> Result<i64> {
        let data_str = serde_json::to_string(data)
            .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
        let conn = self.conn.lock().map_err(map_poison)?;
        conn.execute(
            "INSERT INTO templates (name, type, data) VALUES (?, ?, ?)",
            params![name, svc_type, data_str],
        )
        .map_err(map_err)?;
        Ok(conn.last_insert_rowid())
    }

    /// 全量拉取 (id 升序)。
    pub fn all(&self) -> Result<Vec<Template>> {
        let conn = self.conn.lock().map_err(map_poison)?;
        let mut stmt = conn
            .prepare("SELECT id, name, type, data FROM templates ORDER BY id")
            .map_err(map_err)?;
        let rows = stmt
            .query_map([], |row| {
                let data_str: String = row.get(3)?;
                let data: serde_json::Value = serde_json::from_str(&data_str).unwrap_or(serde_json::Value::Null);
                Ok(Template {
                    id: row.get(0)?,
                    name: row.get(1)?,
                    svc_type: row.get(2)?,
                    data,
                })
            })
            .map_err(map_err)?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r.map_err(map_err)?);
        }
        Ok(out)
    }

    /// 按 id 删, 返是否命中。
    pub fn delete(&self, id: i64) -> Result<bool> {
        let conn = self.conn.lock().map_err(map_poison)?;
        let affected = conn
            .execute("DELETE FROM templates WHERE id = ?", params![id])
            .map_err(map_err)?;
        Ok(affected > 0)
    }
}

fn map_err(e: rusqlite::Error) -> AppError {
    AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))
}

fn map_poison<T>(_: T) -> AppError {
    AppError::Io(std::io::Error::new(
        std::io::ErrorKind::Other,
        "template store mutex poisoned",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use tempfile::tempdir;

    fn store() -> (tempfile::TempDir, TemplateStore) {
        let dir = tempdir().unwrap();
        let s = TemplateStore::open(&dir.path().join("t.db")).unwrap();
        (dir, s)
    }

    /// add -> all 往返: 同库写读一致。
    #[test]
    fn test_add_all_roundtrip() {
        let (_d, s) = store();
        let data = serde_json::json!({"gold": 100});
        let id = s.add("t1", "deposit", &data).unwrap();
        assert!(id > 0);
        let all = s.all().unwrap();
        assert_eq!(all.len(), 1);
        assert_eq!(all[0].name, "t1");
        assert_eq!(all[0].svc_type, "deposit");
        assert_eq!(all[0].data, data);
    }

    /// delete 命中返 true, 再删返 false (幂等空)。
    #[rstest]
    fn test_delete_idempotent() {
        let (_d, s) = store();
        let id = s.add("t", "deposit", &serde_json::json!({})).unwrap();
        assert!(s.delete(id).unwrap());
        assert!(!s.delete(id).unwrap());
        assert!(s.all().unwrap().is_empty());
    }

    /// 多条按 id 升序返。
    #[test]
    fn test_all_ordered_by_id() {
        let (_d, s) = store();
        let a = s.add("a", "deposit", &serde_json::json!({})).unwrap();
        let b = s.add("b", "deposit", &serde_json::json!({})).unwrap();
        let all = s.all().unwrap();
        assert_eq!(all.iter().map(|t| t.id).collect::<Vec<_>>(), vec![a, b]);
    }

    /// open 幂等: 重复 open 同库不重建表, 旧数据保留。
    #[test]
    fn test_open_idempotent_keeps_data() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("t.db");
        {
            let s = TemplateStore::open(&path).unwrap();
            s.add("keep", "deposit", &serde_json::json!({"v": 1})).unwrap();
        }
        let s2 = TemplateStore::open(&path).unwrap();
        let all = s2.all().unwrap();
        assert_eq!(all.len(), 1);
        assert_eq!(all[0].name, "keep");
    }
}
