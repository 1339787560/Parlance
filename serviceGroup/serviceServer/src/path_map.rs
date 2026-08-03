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
    use serde_json::json;
    use std::fs;
    use tempfile::tempdir;

    fn write_config(dir: &Path, value: &serde_json::Value) -> PathBuf {
        let p = dir.join("config.json");
        fs::write(&p, value.to_string()).unwrap();
        p
    }

    #[test]
    fn parses_service_paths() {
        let dir = tempdir().unwrap();
        let cfg = json!({
            "abspath": "D:/game/",
            "service": {
                "zgda": [{ "type": "server_assist", "exe": "ZgdaAssitSvr.exe" }],
                "xzmo": [{ "type": "roomsvrxzmo", "exe": "RoomSvrXzmo.exe" }]
            }
        });
        let p = write_config(dir.path(), &cfg);
        let pm = PathMap::new();
        assert!(pm.refresh(&p).unwrap());

        let zgda = pm.get("zgda_server_assist").expect("zgda path");
        assert_eq!(zgda.path, PathBuf::from("D:/game/zgda/server_assist"));
        assert_eq!(zgda.exe, "ZgdaAssitSvr.exe");

        let xzmo = pm.get("xzmo_roomsvrxzmo").expect("xzmo path");
        assert_eq!(xzmo.path, PathBuf::from("D:/game/xzmo/roomsvrxzmo"));
    }

    #[test]
    fn mtime_unchanged_skips_reparse() {
        let dir = tempdir().unwrap();
        let cfg = json!({ "abspath": "D:/game/", "service": {} });
        let p = write_config(dir.path(), &cfg);
        let pm = PathMap::new();
        assert!(pm.refresh(&p).unwrap());
        assert!(!pm.refresh(&p).unwrap(), "mtime 未变应跳过");
    }

    #[test]
    fn refresh_after_edit() {
        let dir = tempdir().unwrap();
        let cfg = json!({ "abspath": "D:/game/", "service": {} });
        let p = write_config(dir.path(), &cfg);
        let pm = PathMap::new();
        pm.refresh(&p).unwrap();

        let cfg2 = json!({
            "abspath": "D:/game/",
            "service": { "xzmo": [{ "type": "roomsvrxzmo", "exe": "RoomSvrXzmo.exe" }] }
        });
        std::thread::sleep(std::time::Duration::from_millis(20));
        fs::write(&p, cfg2.to_string()).unwrap();
        assert!(pm.refresh(&p).unwrap());
        assert!(pm.get("xzmo_roomsvrxzmo").is_some());
    }

    #[test]
    fn abspath_normalized_with_trailing_sep() {
        let dir = tempdir().unwrap();
        let cfg = json!({ "abspath": "D:/game", "service": {} });
        let p = write_config(dir.path(), &cfg);
        let pm = PathMap::new();
        pm.refresh(&p).unwrap();
        assert_eq!(pm.abspath(), "D:/game/");
    }

    #[test]
    fn valid_roots_covers_all_services() {
        let dir = tempdir().unwrap();
        let cfg = json!({
            "abspath": "D:/game/",
            "service": {
                "a": [{ "type": "t1", "exe": "a.exe" }],
                "b": [{ "type": "t2", "exe": "b.exe" }]
            }
        });
        let p = write_config(dir.path(), &cfg);
        let pm = PathMap::new();
        pm.refresh(&p).unwrap();
        let roots = pm.valid_roots();
        assert_eq!(roots.len(), 2);
    }
}
