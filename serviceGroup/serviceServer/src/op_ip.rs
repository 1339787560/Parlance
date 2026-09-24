//! 操作 IP 记录 —— 「谁最后一次通过本服务页动了这个服务」。
//!
//! 2026-09-24 加: 服务卡片在 modify / update 两行之后展示操作来源 IP。
//! 记录口径 = **经本服务页发出的服务生命周期操作** (启停/重启/强停/部署/删除/热更新),
//! 失败的操作不记 —— 卡片要回答的是「谁最后把它动成功了」。
//!
//! ## 为什么存机器本地 dotfile
//!
//! 记录是**现场数据** (堡垒机上就是堡垒机操作者的 IP)。若存进会被 deploy 包覆盖的位置,
//! dev 端一次 `--push` 就会用本机记录盖掉现场记录。故:
//!   默认路径 = `<config.json 同级>/.service-op-ip.json` (legacy 根, 机器本地),
//!   并在 `make_deploy_pack.py` 显式排除该文件名 (否则 `.json` 后缀会被 INCLUDE_EXT 收进包)。
//! `SERVICESVR_OP_IP_FILE` 可覆盖路径 (测试 / 特殊部署)。
//!
//! ## 只记最后一次
//!
//! 需求只要「最后一次操作的人」, 故每个 service_id 一条, 后写覆盖前写 —— 不攒历史。

use crate::error::Result;
use std::collections::BTreeMap;
use std::net::{IpAddr, SocketAddr};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

/// 状态文件名 (相对于 config.json 所在目录)。
pub const STATE_FILE_NAME: &str = ".service-op-ip.json";

/// 状态文件路径覆盖环境变量。
pub const ENV_STATE_FILE: &str = "SERVICESVR_OP_IP_FILE";

/// 一条操作记录 (只保留最后一次)。
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct OpRecord {
    /// 请求方 IP (已归一化, 见 `client_ip_from`)。
    pub ip: String,
    /// 操作时间 (Unix 秒; 前端按本地时区格式化)。
    pub at: u64,
    /// 动作标签: start / stop / force-stop / restart / delete / deploy / update / start-all。
    pub action: String,
}

/// 操作 IP 存储。`path = None` 时退化为纯内存 (路径解析失败也不让操作报错)。
#[derive(Debug, Default)]
pub struct OpIpStore {
    path: Option<PathBuf>,
    map: Mutex<BTreeMap<String, OpRecord>>,
}

impl OpIpStore {
    /// 从磁盘加载; 文件缺失 / 损坏都退化为空表 (记录是附加信息, 不该阻断服务启动)。
    pub fn load(path: Option<PathBuf>) -> Self {
        let map = match path.as_deref() {
            Some(p) => match std::fs::read_to_string(p) {
                Ok(raw) => match serde_json::from_str::<BTreeMap<String, OpRecord>>(&raw) {
                    Ok(m) => m,
                    Err(e) => {
                        tracing::warn!("操作 IP 记录文件损坏, 作空表处理 ({}): {e}", p.display());
                        BTreeMap::new()
                    }
                },
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => BTreeMap::new(),
                Err(e) => {
                    tracing::warn!("操作 IP 记录读取失败 ({}): {e}", p.display());
                    BTreeMap::new()
                }
            },
            None => BTreeMap::new(),
        };
        Self {
            path,
            map: Mutex::new(map),
        }
    }

    /// 记一条 (覆盖同 service_id 的旧记录) 并落盘。落盘失败只告警 —— 不 fail 用户操作。
    pub fn record(&self, service_id: &str, ip: &str, action: &str, at: u64) {
        let rec = OpRecord {
            ip: ip.to_string(),
            at,
            action: action.to_string(),
        };
        {
            let mut m = match self.map.lock() {
                Ok(m) => m,
                Err(e) => {
                    tracing::warn!("操作 IP 记录锁中毒, 跳过写入: {e}");
                    return;
                }
            };
            m.insert(service_id.to_string(), rec);
        }
        if let Err(e) = self.save() {
            tracing::warn!("操作 IP 记录落盘失败: {e}");
        }
    }

    /// 全量快照 (列表渲染用; 一次加锁取完, 避免逐服务重复加锁)。
    pub fn snapshot(&self) -> BTreeMap<String, OpRecord> {
        self.map
            .lock()
            .map(|m| m.clone())
            .unwrap_or_default()
    }

    fn save(&self) -> Result<()> {
        let Some(path) = self.path.as_deref() else {
            return Ok(()); // 无路径 = 内存态, 无需落盘
        };
        let json = {
            let m = self
                .map
                .lock()
                .map_err(|e| crate::error::AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
            serde_json::to_vec_pretty(&*m)
                .map_err(|e| crate::error::AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?
        };
        // 原子写 (tmp + rename): 本文件无下游目录监视者, 不与游戏配置的「原位写契约」冲突。
        crate::atomic_write::atomic_write_bytes(path, &json)
    }
}

/// 解析状态文件路径: env 覆盖优先, 否则 `<config.json 同级>/<STATE_FILE_NAME>`。
pub fn resolve_path(config_path: &Path, env_override: Option<&str>) -> Option<PathBuf> {
    if let Some(s) = env_override {
        let t = s.trim();
        if !t.is_empty() {
            return Some(PathBuf::from(t));
        }
    }
    config_path.parent().map(|d| d.join(STATE_FILE_NAME))
}

/// 取请求方 IP: `X-Forwarded-For` 首跳 → `X-Real-IP` → 连接对端地址。
///
/// 反代场景取 XFF 最左值 (最初的客户端); 直连场景回落 peer。候选取第一个**可解析**的,
/// 非法值 ("unknown"、空串) 直接跳过而不是把它显示到卡片上。
///
/// 归一化 IPv4-mapped IPv6 (`::ffff:a.b.c.d` → `a.b.c.d`): 监听 `0.0.0.0` 时 Windows
/// 双栈会把 IPv4 客户端报成 v4-mapped 形态, 不剥前缀卡片上会显示 `::ffff:192.168.1.5`。
pub fn client_ip_from(
    xff: Option<&str>,
    real_ip: Option<&str>,
    peer: Option<SocketAddr>,
) -> String {
    let mut cands: Vec<&str> = Vec::new();
    if let Some(x) = xff {
        cands.extend(x.split(',').map(str::trim).filter(|s| !s.is_empty()));
    }
    if let Some(r) = real_ip {
        let t = r.trim();
        if !t.is_empty() {
            cands.push(t);
        }
    }
    for c in cands {
        if let Some(ip) = normalize_ip(c) {
            return ip;
        }
    }
    peer.map(|p| norm_ip(p.ip()))
        .unwrap_or_else(|| "-".to_string())
}

/// 从请求头 + 连接地址取 IP (axum handler 侧入口)。
pub fn client_ip(headers: &axum::http::HeaderMap, peer: Option<SocketAddr>) -> String {
    let hdr = |name: &str| headers.get(name).and_then(|v| v.to_str().ok());
    client_ip_from(
        hdr("x-forwarded-for"),
        hdr("x-real-ip"),
        peer,
    )
}

/// 单个 IP 文本 → 归一化字符串; 不可解析 → None。
fn normalize_ip(raw: &str) -> Option<String> {
    let t = raw.trim();
    if t.is_empty() {
        return None;
    }
    // 也可能带端口 ("1.2.3.4:5678" / "[::1]:80")
    if let Ok(sa) = t.parse::<SocketAddr>() {
        return Some(norm_ip(sa.ip()));
    }
    t.parse::<IpAddr>().ok().map(norm_ip)
}

fn norm_ip(ip: IpAddr) -> String {
    match ip {
        IpAddr::V6(v6) => match v6.to_ipv4_mapped() {
            Some(v4) => v4.to_string(),
            None => v6.to_string(),
        },
        IpAddr::V4(v4) => v4.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn peer(s: &str) -> Option<SocketAddr> {
        Some(s.parse().unwrap())
    }

    /// 测试侧取单条 (生产只走 snapshot, 故 store 不专门暴露 get)。
    fn get_one(store: &OpIpStore, id: &str) -> Option<OpRecord> {
        store.snapshot().remove(id)
    }

    // ---- client_ip_from ----

    #[test]
    fn test_xff_first_hop_wins() {
        assert_eq!(
            client_ip_from(Some("1.2.3.4, 10.0.0.1"), None, peer("127.0.0.1:5000")),
            "1.2.3.4"
        );
    }

    #[test]
    fn test_xff_skips_garbage_entries() {
        // 首跳非法 → 顺延下一个可解析项 (不把 "unknown" 显示到卡片)
        assert_eq!(
            client_ip_from(Some("unknown, 1.2.3.4"), None, None),
            "1.2.3.4"
        );
    }

    #[test]
    fn test_real_ip_used_when_xff_absent() {
        assert_eq!(client_ip_from(None, Some("1.2.3.4"), None), "1.2.3.4");
    }

    #[test]
    fn test_peer_fallback() {
        assert_eq!(client_ip_from(None, None, peer("192.168.1.7:1234")), "192.168.1.7");
    }

    #[test]
    fn test_v4_mapped_ipv6_is_unwrapped() {
        // Windows 双栈 0.0.0.0 监听的真实形态
        assert_eq!(
            client_ip_from(None, None, peer("[::ffff:192.168.1.7]:1234")),
            "192.168.1.7"
        );
        assert_eq!(
            client_ip_from(Some("::ffff:10.1.2.3"), None, None),
            "10.1.2.3"
        );
    }

    #[test]
    fn test_real_ipv6_kept() {
        assert_eq!(client_ip_from(Some("2001:db8::1"), None, None), "2001:db8::1");
        assert_eq!(client_ip_from(None, None, peer("[::1]:5000")), "::1");
    }

    #[test]
    fn test_ip_with_port_is_stripped() {
        assert_eq!(client_ip_from(Some("1.2.3.4:8080"), None, None), "1.2.3.4");
    }

    #[test]
    fn test_all_sources_missing_yields_dash() {
        assert_eq!(client_ip_from(None, None, None), "-");
        assert_eq!(client_ip_from(Some("  "), Some(""), None), "-");
        assert_eq!(client_ip_from(Some("not-an-ip"), None, None), "-");
    }

    // ---- OpIpStore ----

    #[test]
    fn test_record_and_get_last_wins() {
        let store = OpIpStore::load(None); // 内存态
        store.record("xzmo_server_game", "1.1.1.1", "start", 100);
        assert_eq!(get_one(&store, "xzmo_server_game").unwrap().ip, "1.1.1.1");
        store.record("xzmo_server_game", "2.2.2.2", "restart", 200);
        let r = get_one(&store, "xzmo_server_game").unwrap();
        assert_eq!(r.ip, "2.2.2.2");
        assert_eq!(r.action, "restart");
        assert_eq!(r.at, 200);
        assert!(get_one(&store, "nope").is_none());
    }

    #[test]
    fn test_persist_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(STATE_FILE_NAME);

        let store = OpIpStore::load(Some(path.clone()));
        store.record("zgda_server_room", "10.0.0.9", "deploy", 1690000000);

        let reloaded = OpIpStore::load(Some(path.clone()));
        let r = get_one(&reloaded, "zgda_server_room").expect("重载后应保留记录");
        assert_eq!(r.ip, "10.0.0.9");
        assert_eq!(r.action, "deploy");
        assert_eq!(r.at, 1690000000);
    }

    #[test]
    fn test_corrupt_file_degrades_to_empty() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(STATE_FILE_NAME);
        std::fs::write(&path, b"{ this is not json").unwrap();

        let store = OpIpStore::load(Some(path.clone()));
        assert!(store.snapshot().is_empty(), "坏文件应作空表处理, 不 panic");

        // 坏文件之后仍可正常写新记录
        store.record("a_b", "1.2.3.4", "stop", 1);
        assert_eq!(
            get_one(&OpIpStore::load(Some(path)), "a_b").unwrap().ip,
            "1.2.3.4"
        );
    }

    #[test]
    fn test_resolve_path_env_override_and_default() {
        let cfg = Path::new("D:/legacy/config.json");
        assert_eq!(
            resolve_path(cfg, None),
            Some(PathBuf::from("D:/legacy/.service-op-ip.json"))
        );
        assert_eq!(
            resolve_path(cfg, Some("  D:/tmp/op.json ")),
            Some(PathBuf::from("D:/tmp/op.json"))
        );
        // 空白 env → 回落默认
        assert_eq!(
            resolve_path(cfg, Some("   ")),
            Some(PathBuf::from("D:/legacy/.service-op-ip.json"))
        );
    }
}
