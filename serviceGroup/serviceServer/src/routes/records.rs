//! `/api/record/*` — 复盘器数据源统一路由 (SDD running/四川麻将复盘器-数据源)。
//!
//! 两类源 dispatch:
//! - **local**: 本机 FS 直读 (`D:\game\{xzms,xzmo2}\server_game\Record\`)
//! - **oss**: 正式 OSS record 归档 (xzmosvr/xzmssvr 数字 id, subprocess spideOnlineLog)
//!
//! 索引缓存: 进程级 `RwLock<HashMap<(source,date), Vec<RecordMeta>>>`, 无 TTL (record 历史只追加)。
//!
//! hostID 速查表 hardcode (参 oss_hosts.yaml roomsvr + probe 2026-08-06):
//! record service 前缀 = `{代}svr` (gamesvr: xzms→xzmssvr / xzmo→xzmosvr),
//! 数字 id 与 roomsvr 重合 (同机器跨 service 复用 hostID) → region/ver 从 roomsvr 段映射。
//! IP 子目录 (xzmosvr/112.124.x.x 等) = 历史机器仅 log/video, 不列。

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
    /// local / oss
    kind: &'static str,
    /// xzms (六红中) / xzmo (血战血流)
    game: &'static str,
    /// oss 专 (local 项 None): record service 前缀 (gamesvr)
    oss_service: Option<&'static str>,
    /// oss 专: 数字 hostID
    host_id: Option<u32>,
    /// oss 专: 大区/玩法
    region: Option<&'static str>,
    /// oss 专: 金币/银子
    ver: Option<&'static str>,
}

/// 静态源清单 (hostID 速查表 hardcode, 前端源下拉用)。
const SOURCES: &[RecordSource] = &[
    // local 本机 FS
    RecordSource { id: "local-xzms",  label: "本机·六红中",   kind: "local", game: "xzms", oss_service: None, host_id: None, region: None, ver: None },
    RecordSource { id: "local-xzmo2", label: "本机·血血流战", kind: "local", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None },
    // oss-xzms (xzmssvr 血流六红中, 全金币)
    RecordSource { id: "oss-xzms-3291", label: "OSS·六红中1区", kind: "oss", game: "xzms", oss_service: Some("xzmssvr"), host_id: Some(3291), region: Some("血流六红中1区"), ver: Some("金币") },
    RecordSource { id: "oss-xzms-3058", label: "OSS·六红中2区", kind: "oss", game: "xzms", oss_service: Some("xzmssvr"), host_id: Some(3058), region: Some("血流六红中2区"), ver: Some("金币") },
    RecordSource { id: "oss-xzms-3153", label: "OSS·六红中3区", kind: "oss", game: "xzms", oss_service: Some("xzmssvr"), host_id: Some(3153), region: Some("血流六红中3区"), ver: Some("金币") },
    RecordSource { id: "oss-xzms-3335", label: "OSS·六红中4区", kind: "oss", game: "xzms", oss_service: Some("xzmssvr"), host_id: Some(3335), region: Some("血流六红中4区"), ver: Some("金币") },
    // oss-xzmo (xzmosvr 血流血战)
    RecordSource { id: "oss-xzmo-3718", label: "OSS·血战到底", kind: "oss", game: "xzmo", oss_service: Some("xzmosvr"), host_id: Some(3718), region: Some("血战到底"), ver: Some("金币") },
    RecordSource { id: "oss-xzmo-3292", label: "OSS·血流成河", kind: "oss", game: "xzmo", oss_service: Some("xzmosvr"), host_id: Some(3292), region: Some("血流成河"), ver: Some("金币") },
    RecordSource { id: "oss-xzmo-3701", label: "OSS·血战大区", kind: "oss", game: "xzmo", oss_service: Some("xzmosvr"), host_id: Some(3701), region: Some("血战大区"), ver: Some("银子") },
    RecordSource { id: "oss-xzmo-3728", label: "OSS·血流大区", kind: "oss", game: "xzmo", oss_service: Some("xzmosvr"), host_id: Some(3728), region: Some("血流大区"), ver: Some("银子") },
];

fn find_source(id: &str) -> Option<&'static RecordSource> {
    SOURCES.iter().find(|s| s.id == id)
}

#[derive(Serialize, Clone)]
pub struct RecordMeta {
    /// 文件名 (local) / oss key (oss, zip_key::inner)
    pub id: String,
    /// 桌号 (文件名前缀 / oss table_no)
    pub table_no: String,
    /// YYYYMMDD
    pub date: String,
    /// 字节
    pub size: u64,
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

/// `GET /api/record/sources` — 列可用数据源 (含 hostID/region/ver 元数据)。
pub async fn sources() -> Json<Value> {
    Json(json!({ "success": true, "sources": SOURCES }))
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
    /// 文件名 (local) / oss key (zip_key::inner)
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
        _ => Err(AppError::MissingParam("source")),
    }
}

async fn dispatch_get(source: &str, id: &str) -> Result<String> {
    let src = find_source(source).ok_or(AppError::MissingParam("source"))?;
    match src.kind {
        "local" => get_local(local_dir(source).unwrap(), id).await,
        "oss" => get_oss(id).await,
        _ => Err(AppError::MissingParam("source")),
    }
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
    while let Some(e) = rd.next_entry().await? {
        let name = e.file_name().to_string_lossy().to_string();
        if let Some((tno, d)) = parse_record_name(&name) {
            if !date.is_empty() && d != date {
                continue;
            }
            let size = tokio::fs::metadata(e.path()).await.map(|m| m.len()).unwrap_or(0);
            items.push(RecordMeta { id: name, table_no: tno, date: d, size });
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
//         stdout = JSON 索引 (每对局一项, key=zip_key::inner)
//   get:  `--source oss --subdir Record --fetch {key}` (key=id, 含 zip+inner 定位)
//         stdout = record .log 原始字节 (GBK, 交 crate::encoding::decode)
// 滚动保留近 2 日 → 当日 record 在命名日期 +2 日后才全 (list 容忍部分缺)。

const SPIDE_SCRIPT: &str = "spideOnlineLog.py";
const PYTHON: &str = "python";
/// oss subprocess 超时。对齐 spideorder COMMAND_TIMEOUT=300s — OSS 远程 (杭州) +
/// 10MB zip 下载 + 内层 record .log namelist 解析, 3718 单日 1706 项实测 ~185s。
/// 120s 实测不足 (HTTP 404 ServiceUnavailable)。
const OSS_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(300);

#[derive(Deserialize)]
struct OssRecordItem {
    key: String,
    table_no: String,
    date: String,
    size: u64,
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
        args.push(&date_arg);
    }
    let cwd = spide_cwd()?;
    let out = run_spide(&cwd, &args).await?;
    let items: Vec<OssRecordItem> = serde_json::from_slice(&out).map_err(|e| {
        tracing::warn!(
            "oss list JSON 解析失败: {e}; stdout={}",
            String::from_utf8_lossy(&out)
        );
        AppError::ServiceUnavailable
    })?;
    Ok(items
        .into_iter()
        .map(|it| RecordMeta {
            id: it.key,
            table_no: it.table_no,
            date: it.date,
            size: it.size,
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
    let out = tokio::time::timeout(OSS_TIMEOUT, async {
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
    .map_err(|_| {
        tracing::warn!("spideOnlineLog 超时 {OSS_TIMEOUT:?} (args={args:?})");
        AppError::ServiceUnavailable
    })?
    .map_err(|e| {
        tracing::warn!("spideOnlineLog spawn 失败: {e}");
        AppError::ServiceUnavailable
    })?;
    if !out.status.success() {
        tracing::warn!(
            "spideOnlineLog exit={:?} stderr={}",
            out.status.code(),
            String::from_utf8_lossy(&out.stderr)
        );
        return Err(AppError::ServiceUnavailable);
    }
    Ok(out.stdout)
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
        // 两 local + 四 oss-xzms + 四 oss-xzmo = 10
        assert_eq!(SOURCES.len(), 10, "源清单数量");
        assert!(SOURCES.iter().all(|s| !s.id.is_empty() && !s.label.is_empty()));
        // local 项无 oss 元数据
        for s in SOURCES.iter().filter(|s| s.kind == "local") {
            assert!(s.oss_service.is_none() && s.host_id.is_none());
        }
        // oss 项必填 oss_service + host_id + region + ver
        for s in SOURCES.iter().filter(|s| s.kind == "oss") {
            assert!(s.oss_service.is_some(), "oss 源缺 oss_service: {}", s.id);
            assert!(s.host_id.is_some(), "oss 源缺 host_id: {}", s.id);
            assert!(s.region.is_some() && s.ver.is_some());
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
}
