//! service_id -> 路径的静态映射 (mtime 失效缓存)。
//!
//! 对应程序实现文档 "path 与 status 拆分": path 来自 config.json (静态),
//! 不触发任何 Win32 syscall。配置编辑簇路径校验专用, 是点 item 卡顿的根治点。

use crate::config::ConfigDoc;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::RwLock;
use std::time::SystemTime;

/// 单个服务的路径信息 (对应旧 Service.py status_dict 的 path/exe 字段)。
#[derive(Debug, Clone)]
pub struct ServicePath {
    pub service_id: String, // {name}_{type}
    pub name: String,
    pub svc_type: String,
    pub exe: String,
    /// exe 所在目录 = abspath/name/type (旧逻辑 dirname(join(abspath,name,type,exe)))。
    pub path: PathBuf,
}

pub struct PathMap {
    cached: RwLock<Cached>,
}

#[derive(Default)]
struct Cached {
    entries: HashMap<String, ServicePath>,
    mtime: Option<SystemTime>,
    abspath: String,
    doc: Option<ConfigDoc>,
}

impl PathMap {
    pub fn new() -> Self {
        Self {
            cached: RwLock::new(Cached::default()),
        }
    }

    /// 读 config.json; mtime 未变则跳过解析。返回是否实际刷新。
    pub fn refresh(&self, config_path: &Path) -> crate::error::Result<bool> {
        let meta = std::fs::metadata(config_path)?;
        let mtime = meta.modified()?;
        let needs = {
            let c = self.cached.read().unwrap();
            c.mtime != Some(mtime)
        };
        if !needs {
            return Ok(false);
        }
        let raw = std::fs::read_to_string(config_path)?;
        let doc: ConfigDoc = serde_json::from_str(&raw)?;
        let abspath = normalize_abspath(&doc.abspath);
        let mut entries = HashMap::new();
        for (name, list) in &doc.service {
            for entry in list {
                let service_id = format!("{name}_{}", entry.svc_type);
                let path = exe_dir(&abspath, name, &entry.svc_type);
                entries.insert(
                    service_id.clone(),
                    ServicePath {
                        service_id,
                        name: name.clone(),
                        svc_type: entry.svc_type.clone(),
                        exe: entry.exe.clone(),
                        path,
                    },
                );
            }
        }
        let mut c = self.cached.write().unwrap();
        c.entries = entries;
        c.abspath = abspath;
        c.doc = Some(doc);
        c.mtime = Some(mtime);
        Ok(true)
    }

    pub fn get(&self, service_id: &str) -> Option<ServicePath> {
        self.cached.read().unwrap().entries.get(service_id).cloned()
    }

    /// 所有合法服务根路径, 用于路径校验 (替代旧的 startswith)。
    pub fn valid_roots(&self) -> Vec<PathBuf> {
        self.cached
            .read()
            .unwrap()
            .entries
            .values()
            .map(|s| s.path.clone())
            .collect()
    }

    pub fn abspath(&self) -> String {
        self.cached.read().unwrap().abspath.clone()
    }
}

impl Default for PathMap {
    fn default() -> Self {
        Self::new()
    }
}

/// abspath 统一补尾分隔符, 与旧 JsonConfigParser.read_config 对齐。
fn normalize_abspath(p: &str) -> String {
    if p.is_empty() {
        return String::new();
    }
    if p.ends_with('/') || p.ends_with('\\') {
        p.to_string()
    } else {
        format!("{p}/")
    }
}

fn exe_dir(abspath: &str, name: &str, svc_type: &str) -> PathBuf {
    PathBuf::from(abspath).join(name).join(svc_type)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::json;
    use std::fs;
    use tempfile::{tempdir, TempDir};

    /// 写入临时 config.json (pytest tmp_path helper 等价)。
    fn write_config(dir: &Path, value: &serde_json::Value) -> PathBuf {
        let p = dir.join("config.json");
        fs::write(&p, value.to_string()).unwrap();
        p
    }

    /// 两服务 fixture: zgda + xzmo (TempDir 存活由调用方持有)。
    fn config_two_services() -> (TempDir, PathBuf) {
        let dir = tempdir().unwrap();
        let cfg = json!({
            "abspath": "D:/game/",
            "service": {
                "zgda": [{ "type": "server_assist", "exe": "ZgdaAssitSvr.exe" }],
                "xzmo": [{ "type": "roomsvrxzmo", "exe": "RoomSvrXzmo.exe" }]
            }
        });
        let p = write_config(dir.path(), &cfg);
        (dir, p)
    }

    #[test]
    fn test_path_map_parses_service_id_and_dir() {
        // Arrange: 两服务 config
        let (_dir, p) = config_two_services();
        let pm = PathMap::new();

        // Act
        pm.refresh(&p).unwrap();

        // Assert: service_id = {name}_{type}, path = abspath/name/type
        let zgda = pm.get("zgda_server_assist").expect("zgda 服务应存在");
        assert_eq!(zgda.path, PathBuf::from("D:/game/zgda/server_assist"));
        assert_eq!(zgda.exe, "ZgdaAssitSvr.exe");
        let xzmo = pm.get("xzmo_roomsvrxzmo").expect("xzmo 服务应存在");
        assert_eq!(xzmo.path, PathBuf::from("D:/game/xzmo/roomsvrxzmo"));
    }

    #[test]
    fn test_path_map_mtime_unchanged_skips_reparse() {
        // Arrange
        let dir = tempdir().unwrap();
        let p = write_config(dir.path(), &json!({ "abspath": "D:/game/", "service": {} }));
        let pm = PathMap::new();
        pm.refresh(&p).unwrap();

        // Act: 不改 config 再 refresh
        let refreshed = pm.refresh(&p).unwrap();

        // Assert: mtime 未变 -> 跳过
        assert!(!refreshed, "mtime 未变必须跳过重解析");
    }

    #[test]
    fn test_path_map_refresh_after_edit_picks_new_service() {
        // Arrange: 空 config 预热
        let dir = tempdir().unwrap();
        let p = write_config(dir.path(), &json!({ "abspath": "D:/game/", "service": {} }));
        let pm = PathMap::new();
        pm.refresh(&p).unwrap();

        // Act: 改写加 xzmo, 睡 20ms 推进 mtime 精度
        std::thread::sleep(std::time::Duration::from_millis(20));
        fs::write(
            &p,
            json!({
                "abspath": "D:/game/",
                "service": { "xzmo": [{ "type": "roomsvrxzmo", "exe": "RoomSvrXzmo.exe" }] }
            })
            .to_string(),
        )
        .unwrap();
        let refreshed = pm.refresh(&p).unwrap();

        // Assert: mtime 变 -> 重解析, 新服务可见
        assert!(refreshed, "mtime 变化必须重解析");
        assert!(pm.get("xzmo_roomsvrxzmo").is_some(), "新服务应可见");
    }

    /// abspath 尾分隔符规范化矩阵 (与旧 JsonConfigParser.read_config 对齐)。
    #[rstest]
    #[case::trailing_slash("D:/game/", "D:/game/")]
    #[case::no_trailing_sep("D:/game", "D:/game/")]
    #[case::trailing_backslash("D:\\game\\", "D:\\game\\")]
    #[case::empty("", "")]
    fn test_path_map_abspath_normalized(#[case] input: &str, #[case] expected: &str) {
        let dir = tempdir().unwrap();
        let p = write_config(dir.path(), &json!({ "abspath": input, "service": {} }));
        let pm = PathMap::new();
        pm.refresh(&p).unwrap();
        assert_eq!(pm.abspath(), expected);
    }

    #[test]
    fn test_path_map_valid_roots_covers_all_services() {
        let (_dir, p) = config_two_services();
        let pm = PathMap::new();
        pm.refresh(&p).unwrap();
        assert_eq!(pm.valid_roots().len(), 2, "每个服务一个根");
    }
}
