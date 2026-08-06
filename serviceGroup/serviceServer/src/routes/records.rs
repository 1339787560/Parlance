//! `/api/record/*` — 复盘器数据源统一路由 (SDD running/四川麻将复盘器-数据源)。
//!
//! 三类源 dispatch:
//! - **local**: 本机 FS 直读 (`D:\game\{xzms,xzmo2}\server_game\Record\`)
//! - **oss**: 正式 OSS record 归档 (xzmosvr/xzmssvr 数字 id, subprocess spideOnlineLog)
//! - **bastion**: 堡垒机 53/185 servicesvr 代理 (reqwest GET 远端 `/api/record/*`,
//!   近 2 日 OSS 未上传的 record; 需 53/185 部署本同款 servicesvr + env
//!   SERVICESVR_BASTION_<host>_URL)
//!
//! list 返每项含头部元数据 (room_id + players[4 uid] + names[4]) — 供前端按房间/玩家筛。
//! 索引缓存: 进程级 `RwLock<HashMap<(source,date), Vec<RecordMeta>>>`, 无 TTL。
//!
//! hostID 速查表 hardcode (参 oss_hosts.yaml roomsvr + probe 2026-08-06):
//! record service 前缀 = `{代}svr` (gamesvr: xzms→xzmssvr / xzmo→xzmosvr),
//! 数字 id 与 roomsvr 重合 → region/ver 从 roomsvr 段映射。
//! IP 子目录 (xzmosvr/112.124.x.x 等) = 历史机器仅 log/video, 不列。
//!
//! `my_host_id` (env SERVICESVR_HOST_ID, 缺省 "local") 返前端, 用于堡垒机自指判断
//! (bastion-{my_host_id} 源 = 本机, 前端隐, 因 local 已覆盖)。

use std::collections::HashMap;
use std::sync::LazyLock;

use axum::extract::Query;
use axum::Json;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::RwLock;

use crate::error::{AppError, Result};

#[derive(Serialize, Clone)]
struct RecordSource {
    id: &'static str,
    label: &'static str,
    /// local / bastion / oss
    kind: &'static str,
    /// xzms (六红中) / xzmo (血战血流)
    game: &'static str,
    /// oss 专 (local/bastion 项 None): record service 前缀 (gamesvr)
    oss_service: Option<&'static str>,
    /// oss 专: 数字 hostID (大区)
    host_id: Option<u32>,
    /// oss 专: 大区/玩法
    region: Option<&'static str>,
    /// oss 专: 金币/银子
    ver: Option<&'static str>,
    /// bastion 专: 堡垒机代号 ("53"/"185"), 配 env SERVICESVR_BASTION_<host>_URL
    bastion_host: Option<&'static str>,
    /// bastion 专: 远端 servicesvr 的 local source id (local-xzms/local-xzmo2)
    remote_source: Option<&'static str>,
}

/// 静态源清单 (hostID 速查表 hardcode, 前端源下拉用)。
/// local 本机 + oss 8 大区 + bastion 4 (53/185 × xzms/xzmo2)。
const SOURCES: &[RecordSource] = &[
    // local 本机 FS
    RecordSource { id: "local-xzms",  label: "本机·六红中",   kind: "local", game: "xzms", oss_service: None, host_id: None, region: None, ver: None, bastion_host: None, remote_source: None },
    RecordSource { id: "local-xzmo2", label: "本机·血流血战", kind: "local", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: None, remote_source: None },
    // oss-xzms (xzmssvr 血流六红中, 全金币)
    RecordSource { id: "oss-xzms-3291", label: "OSS·六红中1区", kind: "oss", game: "xzms", oss_service: Some("xzmssvr"), host_id: Some(3291), region: Some("血流六红中1区"), ver: Some("金币"), bastion_host: None, remote_source: None },
    RecordSource { id: "oss-xzms-3058", label: "OSS·六红中2区", kind: "oss", game: "xzms", oss_service: Some("xzmssvr"), host_id: Some(3058), region: Some("血流六红中2区"), ver: Some("金币"), bastion_host: None, remote_source: None },
    RecordSource { id: "oss-xzms-3153", label: "OSS·六红中3区", kind: "oss", game: "xzms", oss_service: Some("xzmssvr"), host_id: Some(3153), region: Some("血流六红中3区"), ver: Some("金币"), bastion_host: None, remote_source: None },
    RecordSource { id: "oss-xzms-3335", label: "OSS·六红中4区", kind: "oss", game: "xzms", oss_service: Some("xzmssvr"), host_id: Some(3335), region: Some("血流六红中4区"), ver: Some("金币"), bastion_host: None, remote_source: None },
    // oss-xzmo (xzmosvr 血流血战)
    RecordSource { id: "oss-xzmo-3718", label: "OSS·血战到底", kind: "oss", game: "xzmo", oss_service: Some("xzmosvr"), host_id: Some(3718), region: Some("血战到底"), ver: Some("金币"), bastion_host: None, remote_source: None },
    RecordSource { id: "oss-xzmo-3292", label: "OSS·血流成河", kind: "oss", game: "xzmo", oss_service: Some("xzmosvr"), host_id: Some(3292), region: Some("血流成河"), ver: Some("金币"), bastion_host: None, remote_source: None },
    RecordSource { id: "oss-xzmo-3701", label: "OSS·血战大区", kind: "oss", game: "xzmo", oss_service: Some("xzmosvr"), host_id: Some(3701), region: Some("血战大区"), ver: Some("银子"), bastion_host: None, remote_source: None },
    RecordSource { id: "oss-xzmo-3728", label: "OSS·血流大区", kind: "oss", game: "xzmo", oss_service: Some("xzmosvr"), host_id: Some(3728), region: Some("血流大区"), ver: Some("银子"), bastion_host: None, remote_source: None },
    // bastion (堡垒机 53/185 近 2 日 record, OSS 未上传; reqwest 代理远端 servicesvr)
    // proxy_url 走 env SERVICESVR_BASTION_<host>_URL (部署时配, 避硬编 IP)
    RecordSource { id: "bastion-53-xzms",  label: "53·六红中",   kind: "bastion", game: "xzms", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("53"),  remote_source: Some("local-xzms") },
    RecordSource { id: "bastion-53-xzmo2", label: "53·血血流战", kind: "bastion", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("53"),  remote_source: Some("local-xzmo2") },
    RecordSource { id: "bastion-185-xzms",  label: "185·六红中",  kind: "bastion", game: "xzms", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("185"), remote_source: Some("local-xzms") },
    RecordSource { id: "bastion-185-xzmo2", label: "185·血血流战",kind: "bastion", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("185"), remote_source: Some("local-xzmo2") },
];

fn find_source(id: &str) -> Option<&'static RecordSource> {
    SOURCES.iter().find(|s| s.id == id)
}

#[derive(Serialize, Deserialize, Clone)]
pub struct RecordMeta {
    /// 文件名 (local) / oss key (oss, zip_key::inner) / 远端文件名 (bastion 透传)
    pub id: String,
    pub table_no: String,
    /// YYYYMMDD
    pub date: String,
    pub size: u64,
    /// 头部元数据 (list 读前 2KB 解析, 供前端房间/玩家筛; #[serde(default)] 容错远端旧版缺字段)
    #[serde(default)]
    pub room_id: String,
    #[serde(default)]
    pub players: Vec<String>,
    #[serde(default)]
    pub names: Vec<String>,
    #[serde(default)]
    pub timestamp: u64,
}

type CacheKey = (String, String);
static CACHE: LazyLock<RwLock<HashMap<CacheKey, Vec<RecordMeta>>>> =
    LazyLock::new(|| RwLock::new(HashMap::new()));

/// local 源 Record 根目录。None = 非 local 源。
fn local_dir(source: &str) -> Option<&'static str> {
    match source {
        "local-xzms" => Some(r"D:\game\xzms\server_game\Record"),
        "local-xzmo2" => Some(r"D:\game\xzmo2\server_game\Record"),
        _ => None,
    }
}

/// `GET /api/record/sources` — 列可用数据源 + 本机 host_id (前端隐本机 bastion 源)。
pub async fn sources() -> Json<Value> {
    let my_host_id =
        std::env::var("SERVICESVR_HOST_ID").unwrap_or_else(|_| "local".to_string());
    Json(json!({ "success": true, "sources": SOURCES, "my_host_id": my_host_id }))
}

#[derive(Deserialize)]
pub struct ListParams {
    pub source: String,
    /// YYYYMMDD; 缺省 = 该源全部日期 (oss = today, 由 spideOnlineLog 默认)
    pub date: Option<String>,
}

/// `GET /api/record/list?source=&date=` — 列日索引 (内存缓存命中秒返)。
pub async fn list(Query(p): Query<ListParams>) -> Result<Json<Value>> {
    if p.source.is_empty() {
        return Err(AppError::MissingParam("source"));
    }
    find_source(&p.source).ok_or(AppError::MissingParam("source"))?;
    let date = p.date.clone().unwrap_or_default();
    let key = (p.source.clone(), date.clone());

    {
        let cache = CACHE.read().await;
        if let Some(items) = cache.get(&key) {
            return Ok(Json(json!({
                "success": true, "source": key.0, "date": key.1,
                "items": items, "cached": true,
            })));
        }
    }

    let items = dispatch_list(&p.source, &date).await?;
    CACHE.write().await.insert(key.clone(), items.clone());
    Ok(Json(json!({
        "success": true, "source": key.0, "date": key.1,
        "items": items, "cached": false,
    })))
}

#[derive(Deserialize)]
pub struct GetParams {
    pub source: String,
    /// 文件名 (local) / oss key (zip_key::inner) / bastion 远端文件名
    pub id: String,
}

/// `GET /api/record/get?source=&id=` — 取单条 record 文本 (GBK→UTF-8)。
pub async fn get(Query(p): Query<GetParams>) -> Result<Json<Value>> {
    if p.source.is_empty() {
        return Err(AppError::MissingParam("source"));
    }
    if p.id.is_empty() {
        return Err(AppError::MissingParam("id"));
    }
    let text = dispatch_get(&p.source, &p.id).await?;
    Ok(Json(json!({
        "success": true, "source": p.source, "id": p.id, "content": text,
    })))
}

// ── dispatch ─────────────────────────────────────────────────────────────────

async fn dispatch_list(source: &str, date: &str) -> Result<Vec<RecordMeta>> {
    let src = find_source(source).ok_or(AppError::MissingParam("source"))?;
    match src.kind {
        "local" => list_local(local_dir(source).unwrap(), date).await,
        "oss" => list_oss(src, date).await,
        "bastion" => list_bastion(src, date).await,
        _ => Err(AppError::MissingParam("source")),
    }
}

async fn dispatch_get(source: &str, id: &str) -> Result<String> {
    let src = find_source(source).ok_or(AppError::MissingParam("source"))?;
    match src.kind {
        "local" => get_local(local_dir(source).unwrap(), id).await,
        "oss" => get_oss(id).await,
        "bastion" => get_bastion(src, id).await,
        _ => Err(AppError::MissingParam("source")),
    }
}

// ── 头部解析 (RoomID + 4 ChairNO uid + 4 Name) ──────────────────────────────

/// 解析 record 头部 (前 2KB 文本) → (room_id, players[4], names[4])。
/// 用于 list 增返元数据供前端按房间/玩家筛。格式参 memory `xzms-record-log-format`:
/// `RoomID <id>` / `ChairNO <idx> <uid> ...` / `Name <idx> <name>`。
fn parse_record_head(text: &str) -> (String, Vec<String>, Vec<String>, u64) {
    let mut room_id = String::new();
    let mut players = vec![String::new(); 4];
    let mut names = vec![String::new(); 4];
    let mut timestamp: u64 = 0;
    for line in text.lines().take(40) {
        if let Some(v) = line.strip_prefix("RoomID ") {
            room_id = v.split_whitespace().next().unwrap_or("").to_string();
        } else if let Some(v) = line.strip_prefix("Timestamp ") {
            timestamp = v.split_whitespace().next().and_then(|s| s.parse().ok()).unwrap_or(0);
        } else if let Some(rest) = line.strip_prefix("ChairNO ") {
            let parts: Vec<&str> = rest.split_whitespace().collect();
            if parts.len() >= 2 {
                if let Ok(i) = parts[0].parse::<usize>() {
                    if i < 4 {
                        players[i] = parts[1].to_string();
                    }
                }
            }
        } else if let Some(rest) = line.strip_prefix("Name ") {
            let parts: Vec<&str> = rest.splitn(2, ' ').collect();
            if parts.len() >= 2 {
                if let Ok(i) = parts[0].parse::<usize>() {
                    if i < 4 {
                        names[i] = parts[1].to_string();
                    }
                }
            }
        }
    }
    (room_id, players, names, timestamp)
}

// ── local 源 ─────────────────────────────────────────────────────────────────

async fn list_local(dir: &str, date: &str) -> Result<Vec<RecordMeta>> {
    let root = std::path::Path::new(dir);
    if !root.is_dir() {
        tracing::warn!("local Record 目录不存在: {dir}");
        return Err(AppError::NotFound);
    }
    let mut items = Vec::new();
    let mut rd = tokio::fs::read_dir(root).await?;
    use tokio::io::AsyncReadExt;
    while let Some(e) = rd.next_entry().await? {
        let name = e.file_name().to_string_lossy().to_string();
        if let Some((tno, d)) = parse_record_name(&name) {
            if !date.is_empty() && d != date {
                continue;
            }
            let size = tokio::fs::metadata(e.path()).await.map(|m| m.len()).unwrap_or(0);
            // 读前 2KB 头部解析 room_id + 玩家 (供前端筛)
            let (room_id, players, names, timestamp) = match tokio::fs::File::open(e.path()).await {
                Ok(mut f) => {
                    let mut buf = vec![0u8; 2048];
                    let n = f.read(&mut buf).await.unwrap_or(0);
                    let txt = crate::encoding::decode(&buf[..n]).content;
                    parse_record_head(&txt)
                }
                Err(_) => (String::new(), vec![String::new(); 4], vec![String::new(); 4], 0),
            };
            items.push(RecordMeta {
                id: name, table_no: tno, date: d, size, room_id, players, names, timestamp,
            });
        }
    }
    items.sort_by(|a, b| a.table_no.cmp(&b.table_no).then(a.id.cmp(&b.id)));
    Ok(items)
}

async fn get_local(dir: &str, id: &str) -> Result<String> {
    let root = std::path::Path::new(dir);
    let path = root.join(id);
    // 防路径穿越: id 必须是 root 直接子文件
    if !path.starts_with(root) || path.parent() != Some(root) {
        return Err(AppError::Forbidden);
    }
    if !path.is_file() {
        return Err(AppError::NotFound);
    }
    let bytes = tokio::fs::read(&path).await?;
    Ok(crate::encoding::decode(&bytes).content)
}

/// 解析 `{tableNO}_{YYYYMMDD}.log` 文件名。
fn parse_record_name(name: &str) -> Option<(String, String)> {
    let stem = name.strip_suffix(".log")?;
    let (tno, d) = stem.split_once('_')?;
    if !tno.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    if d.len() != 8 || !d.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some((tno.to_string(), d.to_string()))
}

// ── oss 源 (subprocess spideOnlineLog) ──────────────────────────────────────
//
// 调 `python spideOnlineLog.py` (exe 同目录, 走 PATH python — 该解释器装了 oss2/CredsManager)。
// 两模式:
//   list: `--source oss --service {oss_service} --host {host_id} --subdir Record --json --no-download [date]`
//         stdout = JSON 索引 (每对局一项, 含 room_id/players/names, key=zip_key::inner)
//   get:  `--source oss --subdir Record --fetch {key}` (key=id, 含 zip+inner 定位)
//         stdout = record .log 原始字节 (GBK, 交 crate::encoding::decode)
// 滚动保留近 2 日 → 当日 record 在命名日期 +2 日后才全 (list 容忍部分缺)。

const SPIDE_SCRIPT: &str = "spideOnlineLog.py";
const PYTHON: &str = "python";
/// oss subprocess 超时。对齐 spideorder COMMAND_TIMEOUT=300s — OSS 远程 (杭州) +
/// 10MB zip 下载 + 内层 record .log 头部解析 (流式 2KB), 3718 单日 1706 项实测 ~215s。
/// 120s 实测不足 (HTTP 404 ServiceUnavailable)。
const OSS_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(300);

#[derive(Deserialize)]
struct OssRecordItem {
    key: String,
    table_no: String,
    date: String,
    size: u64,
    #[serde(default)]
    room_id: String,
    #[serde(default)]
    players: Vec<String>,
    #[serde(default)]
    names: Vec<String>,
    #[serde(default)]
    timestamp: u64,
}

async fn list_oss(src: &RecordSource, date: &str) -> Result<Vec<RecordMeta>> {
    let svc = src.oss_service.unwrap();
    let host_str = src.host_id.unwrap().to_string();
    let date_arg = format_date_arg(date); // "" or YYYY-MM-DD
    let mut args: Vec<&str> = vec![
        "--source", "oss", "--service", svc, "--host", &host_str,
        "--subdir", "Record", "--json", "--no-download",
    ];
    if !date_arg.is_empty() {
        // spideOnlineLog _parse_dates 单参 = start..today (多日扫, 致 1706 项多日累加 + 200s 超时);
        // 传两同参 = start=end=date 单日 (zip 实际 ~4 对局 .log)
        args.push(&date_arg);
        args.push(&date_arg);
    }
    let cwd = spide_cwd().map_err(|e| { write_dbg_log("spide_cwd_err", &[], &format!("{:?}", e)); e })?;
    let out = run_spide(&cwd, &args).await?;
    let items: Vec<OssRecordItem> = serde_json::from_slice(&out).map_err(|e| {
        let stdout_str = String::from_utf8_lossy(&out);
        let head = &stdout_str[..stdout_str.len().min(400)];
        tracing::warn!("oss list JSON 解析失败: {e}; stdout={head}");
        write_dbg_log("json_err", &args, &format!("{e}; stdout_head={head}"));
        AppError::ServiceUnavailable
    })?;
    Ok(items
        .into_iter()
        .map(|it| RecordMeta {
            id: it.key,
            table_no: it.table_no,
            date: it.date,
            size: it.size,
            room_id: it.room_id,
            players: pad4(it.players),
            names: pad4(it.names),
            timestamp: it.timestamp,
        })
        .collect())
}

async fn get_oss(id: &str) -> Result<String> {
    let cwd = spide_cwd()?;
    let out = run_spide(&cwd, &["--source", "oss", "--subdir", "Record", "--fetch", id]).await?;
    Ok(crate::encoding::decode(&out).content)
}

/// 跑 spideOnlineLog.py, 返 stdout bytes。失败 (非零 exit / spawn 失败 / 超时) → ServiceUnavailable。
async fn run_spide(cwd: &std::path::Path, args: &[&str]) -> Result<Vec<u8>> {
    let out = match tokio::time::timeout(OSS_TIMEOUT, async {
        tokio::process::Command::new(PYTHON)
            .arg(SPIDE_SCRIPT)
            .args(args)
            .current_dir(cwd)
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .output()
            .await
    })
    .await
    {
        Ok(Ok(o)) => o,
        Ok(Err(e)) => {
            tracing::warn!("spideOnlineLog spawn 失败: {e}");
            write_dbg_log("spawn_err", args, &e.to_string());
            return Err(AppError::ServiceUnavailable);
        }
        Err(_) => {
            tracing::warn!("spideOnlineLog 超时 {OSS_TIMEOUT:?} (args={args:?})");
            write_dbg_log("timeout", args, "");
            return Err(AppError::ServiceUnavailable);
        }
    };
    if !out.status.success() {
        let stderr_str = String::from_utf8_lossy(&out.stderr);
        tracing::warn!("spideOnlineLog exit={:?} stderr={}", out.status.code(), stderr_str);
        write_dbg_log("exit", args, &stderr_str);
        return Err(AppError::ServiceUnavailable);
    }
    write_dbg_log("ok", args, &format!("stdout_len={}", out.stdout.len()));
    Ok(out.stdout)
}

/// 临时诊断: 写 subprocess stderr/exit/args 到 servicesvr-debug.log (exe 同目录), 定位 oss/bastion 拉取失败。
fn write_dbg_log(kind: &str, args: &[&str], stderr: &str) {
    use std::io::Write;
    let dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| std::path::PathBuf::from("."));
    let path = dir.join("servicesvr-debug.log");
    let content = format!("kind={kind} args={args:?} stderr={stderr}\n");
    let _ = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .and_then(|mut f| f.write_all(content.as_bytes()));
}

/// spideOnlineLog.py 工作目录 = servicesvr exe 同目录 (脚本与 exe 同放, 参 spideorder)。
fn spide_cwd() -> Result<std::path::PathBuf> {
    let exe = std::env::current_exe()?;
    let dir = exe.parent().ok_or(AppError::NotFound)?.to_path_buf();
    if !dir.join(SPIDE_SCRIPT).exists() {
        tracing::warn!("spideOnlineLog.py 不在 exe 同目录: {}", dir.display());
        return Err(AppError::NotFound);
    }
    Ok(dir)
}

/// YYYYMMDD → YYYY-MM-DD (spideOnlineLog 位置参格式); 空串 / 非法原样返。
fn format_date_arg(date: &str) -> String {
    if date.len() == 8 && date.bytes().all(|b| b.is_ascii_digit()) {
        format!("{}-{}-{}", &date[0..4], &date[4..6], &date[6..8])
    } else {
        date.to_string()
    }
}

/// 不足 4 元素补空串 (players/names 容错)。
fn pad4(mut v: Vec<String>) -> Vec<String> {
    while v.len() < 4 {
        v.push(String::new());
    }
    v
}

// ── bastion 源 (reqwest 代理远端 servicesvr) ────────────────────────────────
//
// 近 2 日 OSS 未上传的 record → 走堡垒机 53/185 本机 FS (远端 servicesvr local 源)。
// 需 53/185 部署本同款 servicesvr (含 records.rs) + env SERVICESVR_BASTION_<host>_URL。
// 远端 list/get 返同结构 RecordMeta (含 room_id/players/names), 本机透传。

/// bastion 代理超时 (远端 servicesvr local FS 快; 远端 oss 不经 bastion)。
const BASTION_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);

fn bastion_proxy_url(src: &RecordSource) -> Result<String> {
    let host = src.bastion_host.unwrap();
    let key = format!("SERVICESVR_BASTION_{}_URL", host);
    std::env::var(&key).map_err(|_| {
        tracing::warn!("bastion env {key} 未设 (源 {})", src.id);
        AppError::ServiceUnavailable
    })
}

async fn list_bastion(src: &RecordSource, date: &str) -> Result<Vec<RecordMeta>> {
    let proxy = bastion_proxy_url(src)?;
    let remote = src.remote_source.unwrap();
    let client = reqwest::Client::builder()
        .timeout(BASTION_TIMEOUT)
        .build()
        .map_err(|_| AppError::ServiceUnavailable)?;
    let mut req = client
        .get(format!("{proxy}/api/record/list"))
        .query(&[("source", remote)]);
    if !date.is_empty() {
        req = req.query(&[("date", date)]);
    }
    let resp = req.send().await.map_err(|e| {
        tracing::warn!("bastion list {} 连接失败: {e}", src.id);
        AppError::ServiceUnavailable
    })?;
    let bytes = resp.bytes().await.map_err(|_| AppError::ServiceUnavailable)?;
    let v: Value = serde_json::from_slice(&bytes).map_err(|_| AppError::ServiceUnavailable)?;
    if !v.get("success").and_then(|s| s.as_bool()).unwrap_or(false) {
        return Err(AppError::ServiceUnavailable);
    }
    let items_val = v.get("items").cloned().unwrap_or(Value::Array(vec![]));
    serde_json::from_value(items_val).map_err(|_| AppError::ServiceUnavailable)
}

async fn get_bastion(src: &RecordSource, id: &str) -> Result<String> {
    let proxy = bastion_proxy_url(src)?;
    let remote = src.remote_source.unwrap();
    let client = reqwest::Client::builder()
        .timeout(BASTION_TIMEOUT)
        .build()
        .map_err(|_| AppError::ServiceUnavailable)?;
    let resp = client
        .get(format!("{proxy}/api/record/get"))
        .query(&[("source", remote), ("id", id)])
        .send()
        .await
        .map_err(|e| {
            tracing::warn!("bastion get {} 连接失败: {e}", src.id);
            AppError::ServiceUnavailable
        })?;
    let bytes = resp.bytes().await.map_err(|_| AppError::ServiceUnavailable)?;
    let v: Value = serde_json::from_slice(&bytes).map_err(|_| AppError::ServiceUnavailable)?;
    v.get("content")
        .and_then(|c| c.as_str())
        .map(|s| s.to_string())
        .ok_or(AppError::ServiceUnavailable)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_name_ok() {
        assert_eq!(
            parse_record_name("11883_20260209.log"),
            Some(("11883".into(), "20260209".into()))
        );
    }

    #[test]
    fn parse_name_rejects_bad() {
        assert_eq!(parse_record_name("11883_20260209.txt"), None);
        assert_eq!(parse_record_name("abc_20260209.log"), None);
        assert_eq!(parse_record_name("11883_2026020.log"), None);
        assert_eq!(parse_record_name("11883_20260209"), None);
    }

    #[test]
    fn local_dir_maps_known_sources() {
        assert_eq!(local_dir("local-xzms"), Some(r"D:\game\xzms\server_game\Record"));
        assert_eq!(local_dir("local-xzmo2"), Some(r"D:\game\xzmo2\server_game\Record"));
        assert_eq!(local_dir("oss-xzms-3291"), None);
    }

    #[test]
    fn sources_table_sanity() {
        // 2 local + 4 oss-xzms + 4 oss-xzmo + 4 bastion = 14
        assert_eq!(SOURCES.len(), 14, "源清单数量");
        assert!(SOURCES.iter().all(|s| !s.id.is_empty() && !s.label.is_empty()));
        // local 项无 oss/bastion 元数据
        for s in SOURCES.iter().filter(|s| s.kind == "local") {
            assert!(s.oss_service.is_none() && s.host_id.is_none() && s.bastion_host.is_none());
        }
        // oss 项必填 oss_service + host_id + region + ver
        for s in SOURCES.iter().filter(|s| s.kind == "oss") {
            assert!(s.oss_service.is_some(), "oss 源缺 oss_service: {}", s.id);
            assert!(s.host_id.is_some(), "oss 源缺 host_id: {}", s.id);
            assert!(s.region.is_some() && s.ver.is_some());
        }
        // bastion 项必填 bastion_host + remote_source
        for s in SOURCES.iter().filter(|s| s.kind == "bastion") {
            assert!(s.bastion_host.is_some(), "bastion 源缺 bastion_host: {}", s.id);
            assert!(s.remote_source.is_some(), "bastion 源缺 remote_source: {}", s.id);
        }
        // id 唯一
        let mut ids: Vec<&str> = SOURCES.iter().map(|s| s.id).collect();
        ids.sort();
        let before = ids.len();
        ids.dedup();
        assert_eq!(ids.len(), before, "source id 重复");
    }

    #[rstest::rstest]
    #[case("", "")]
    #[case("20250618", "2025-06-18")]
    #[case("2025061", "2025061")]
    fn fmt_date_arg(#[case] input: &str, #[case] want: &str) {
        assert_eq!(format_date_arg(input), want);
    }

    #[test]
    fn parse_head_extracts_room_players_names() {
        let txt = "Version 1.1\r\nTimestamp 1750198483\r\nRoomID 31966\r\nTableNO 2\r\n\
ChairNO 0 255452784 2112 -1\r\nChairNO 1 259461239 1073741824 0\r\n\
ChairNO 2 259461227 1073741824 6\r\nChairNO 3 259461213 1073741824 0\r\n\
Flags 7\r\nName 0 玩家A\r\nName 1 玩家B\r\nName 2 玩家C\r\nName 3 玩家D\r\n";
        let (room, players, names, ts) = parse_record_head(txt);
        assert_eq!(room, "31966");
        assert_eq!(ts, 1750198483);
        assert_eq!(players, vec!["255452784", "259461239", "259461227", "259461213"]);
        assert_eq!(names, vec!["玩家A", "玩家B", "玩家C", "玩家D"]);
    }
}
