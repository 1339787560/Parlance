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
/// local 本机 + oss 8 大区 + bastion 6 (53/185 × xzmo金币/xzmo2银子)。
/// xzmo = 金币版血流血战, xzmo2 = 银子版血流血战 (两者互斥运行, 均活跃服务)。
const SOURCES: &[RecordSource] = &[
    // local 本机 FS (sources() 按目录存在性过滤, 未部署的自然隐藏)
    RecordSource { id: "local-xzms",  label: "本机·六红中",     kind: "local", game: "xzms", oss_service: None, host_id: None, region: None, ver: None, bastion_host: None, remote_source: None },
    RecordSource { id: "local-xzmo",  label: "本机·血流血战(金币)", kind: "local", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: None, remote_source: None },
    RecordSource { id: "local-xzmo2", label: "本机·血流血战(银子)", kind: "local", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: None, remote_source: None },
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
    RecordSource { id: "bastion-53-xzms",   label: "53·六红中",        kind: "bastion", game: "xzms", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("53"),  remote_source: Some("local-xzms") },
    RecordSource { id: "bastion-53-xzmo",   label: "53·血流血战(金币)", kind: "bastion", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("53"),  remote_source: Some("local-xzmo") },
    RecordSource { id: "bastion-53-xzmo2",  label: "53·血流血战(银子)", kind: "bastion", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("53"),  remote_source: Some("local-xzmo2") },
    RecordSource { id: "bastion-185-xzms",  label: "185·六红中",       kind: "bastion", game: "xzms", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("185"), remote_source: Some("local-xzms") },
    RecordSource { id: "bastion-185-xzmo",  label: "185·血流血战(金币)", kind: "bastion", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("185"), remote_source: Some("local-xzmo") },
    RecordSource { id: "bastion-185-xzmo2", label: "185·血流血战(银子)", kind: "bastion", game: "xzmo", oss_service: None, host_id: None, region: None, ver: None, bastion_host: Some("185"), remote_source: Some("local-xzmo2") },
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
/// xzmo = 金币版, xzmo2 = 银子版 (互斥运行; 目录常驻, 谁在跑数据就落在谁目录)。
fn local_dir(source: &str) -> Option<&'static str> {
    match source {
        "local-xzms" => Some(r"D:\game\xzms\server_game\Record"),
        "local-xzmo" => Some(r"D:\game\xzmo\server_game\Record"),
        "local-xzmo2" => Some(r"D:\game\xzmo2\server_game\Record"),
        _ => None,
    }
}

/// `GET /api/record/sources` — 列可用数据源 + 本机 host_id (前端隐本机 bastion 源)。
/// local 源按目录存在性过滤 (本机未部署的服务如 xzmo 不显示; 部署机上自然出现)。
pub async fn sources() -> Json<Value> {
    let my_host_id =
        std::env::var("SERVICESVR_HOST_ID").unwrap_or_else(|_| "local".to_string());
    let visible: Vec<&RecordSource> = SOURCES
        .iter()
        .filter(|s| s.kind != "local" || local_dir(s.id).is_some_and(|d| std::path::Path::new(d).is_dir()))
        .collect();
    Json(json!({ "success": true, "sources": visible, "my_host_id": my_host_id }))
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

// ── 一键导出做牌 (复盘器 → 目标服务 test_<名称>.ini) ────────────────────────

#[derive(Deserialize)]
pub struct SaveMakecardReq {
    /// 当前 record 数据源 (local-*/bastion-*); 决定写入哪台机器哪个服务
    pub source: String,
    /// 做牌名称 (短名, 与做牌器一致: 忽略 test_ 前缀与 .ini 后缀, 中文可用)
    pub name: String,
    /// test.ini [Card] 段文本 (Total=| 分隔)
    pub content: String,
    /// 关联 record 文件名 (可选; 写 `; Rec=` 注释行, autotest 据此反向定位剧本)
    #[serde(default)]
    pub record_id: Option<String>,
    /// 关联局序 0 起 (可选)
    #[serde(default)]
    pub round: Option<usize>,
}

/// `; Rec=<source>|<record_id>|<round>` — test_*.ini 尾部关联行 (`;` 注释,
/// 引擎与做牌器均忽略), autotest 读它反查复盘剧本 (script 端点)。
fn rec_line(source: &str, id: &str, round: usize) -> String {
    format!("; Rec={source}|{id}|{round}")
}

/// 解析 test_*.ini 里的 `; Rec=` 行 → (source, record_id, round)。无关联 → None。
fn parse_rec_line(text: &str) -> Option<(String, String, usize)> {
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("; Rec=") {
            let p: Vec<&str> = rest.split('|').collect();
            if p.len() == 3 {
                let round = p[2].trim().parse().unwrap_or(0);
                return Some((p[0].to_string(), p[1].to_string(), round));
            }
        }
    }
    None
}

/// `POST /api/record/save_makecard` — 复盘器一键导出做牌到相同服务。
///
/// 写 `<服务根>/test_<名称>.ini` (服务根 = local_dir 的 Record 上级)。
/// - local 源: 本机 FS 直写 (GBK, 与 test.ini 家族一致; 新建文件)
/// - bastion 源: 转发远端同款端点 (远端需部署本版本; 否则 404/失败提示更新)
/// - oss 源: 不支持 (归档无服务), 提示走剪贴板
/// 名称仅允许非路径分隔字符, 防 `..\` 穿越。
pub async fn save_makecard(Json(req): Json<SaveMakecardReq>) -> Result<Json<Value>> {
    let src = find_source(&req.source).ok_or(AppError::MissingParam("source"))?;
    let name = req.name.trim();
    if name.is_empty() {
        return Err(AppError::MissingParam("name"));
    }
    if name.chars().any(|c| r#"\/:*?"<>|"#.contains(c)) {
        return Err(AppError::BadRequest("名称含非法字符 (\\/:*?\"<>|)".into()));
    }
    let file_name = format!("test_{name}.ini");
    // 关联行: 有 record_id 才写 (纯手搓做牌无关联)
    let content = match (&req.record_id, req.round) {
        (Some(id), Some(r)) => format!("{}\r\n{}\r\n", req.content.trim_end(), rec_line(&req.source, id, r)),
        _ => req.content.clone(),
    };

    match src.kind {
        "local" => {
            let record_dir = std::path::Path::new(local_dir(&req.source).unwrap());
            let svc_root = record_dir.parent().ok_or(AppError::NotFound)?;
            let path = svc_root.join(&file_name);
            let bytes = crate::encoding::encode(&content, "gbk")?;
            tokio::fs::write(&path, &bytes).await?;
            tracing::info!("save_makecard: {} → {}", src.id, path.display());
            Ok(Json(json!({
                "success": true, "source": req.source, "file": file_name,
                "path": path.display().to_string(),
            })))
        }
        "bastion" => {
            let proxy = bastion_proxy_url(src)?;
            let remote = src.remote_source.unwrap();
            let client = reqwest::Client::builder()
                .timeout(BASTION_TIMEOUT)
                .build()
                .map_err(|_| AppError::ServiceUnavailable)?;
            let body = serde_json::to_string(&json!({
                "source": remote, "name": name, "content": content,
                "record_id": req.record_id, "round": req.round,
            }))
            .map_err(|_| AppError::ServiceUnavailable)?;
            let resp = client
                .post(format!("{proxy}/api/record/save_makecard"))
                .header(reqwest::header::CONTENT_TYPE, "application/json")
                .body(body)
                .send()
                .await
                .map_err(|e| {
                    tracing::warn!("bastion save_makecard {} 连接失败: {e}", src.id);
                    AppError::ServiceUnavailable
                })?;
            let bytes = resp.bytes().await.map_err(|_| AppError::ServiceUnavailable)?;
            let v: Value = serde_json::from_slice(&bytes).map_err(|_| AppError::ServiceUnavailable)?;
            if !v.get("success").and_then(|s| s.as_bool()).unwrap_or(false) {
                return Err(AppError::ServiceUnavailable);
            }
            Ok(Json(json!({
                "success": true, "source": req.source, "file": file_name,
                "path": v.get("path").cloned().unwrap_or(Value::String(file_name)),
            })))
        }
        _ => Err(AppError::BadRequest(
            "oss 源无对应服务, 请用「📤 做牌」复制后到做牌器粘贴".into(),
        )),
    }
}

#[derive(Serialize)]
struct MakecardEntry {
    /// 短名 (去 test_ 前缀与 .ini 后缀)
    name: String,
    /// 文件名 test_<name>.ini
    file: String,
    /// 关联 record 源 id (local-xzmo2 等)
    source: String,
    /// 关联 record 文件名
    record_id: String,
    /// 关联局序 (0 起)
    round: usize,
    /// Total 行 (cardid|...; 无 Total 的文件跳过)
    total: String,
}

/// `GET /api/record/makecards?source=` — 列该服务下带 record 关联 (`; Rec=`)
/// 的 test_*.ini (复盘器直存产物), 供 autotest 选择「做牌+剧本」二元组。
pub async fn makecards(Query(p): Query<ListParams>) -> Result<Json<Value>> {
    let src = find_source(&p.source).ok_or(AppError::MissingParam("source"))?;
    match src.kind {
        "local" => {
            let record_dir = std::path::Path::new(local_dir(&p.source).unwrap());
            let svc_root = record_dir.parent().ok_or(AppError::NotFound)?;
            let mut items = Vec::new();
            let mut rd = tokio::fs::read_dir(svc_root).await?;
            while let Some(e) = rd.next_entry().await? {
                let fname = e.file_name().to_string_lossy().to_string();
                let Some(stem) = fname.strip_prefix("test_").and_then(|s| s.strip_suffix(".ini")) else {
                    continue;
                };
                let bytes = tokio::fs::read(e.path()).await.unwrap_or_default();
                let text = crate::encoding::decode(&bytes).content;
                let Some((src_id, record_id, round)) = parse_rec_line(&text) else {
                    continue;
                };
                let total = text
                    .lines()
                    .find_map(|l| l.strip_prefix("Total="))
                    .unwrap_or("")
                    .trim()
                    .to_string();
                if total.is_empty() {
                    continue;
                }
                items.push(MakecardEntry {
                    name: stem.to_string(),
                    file: fname,
                    source: src_id,
                    record_id,
                    round,
                    total,
                });
            }
            items.sort_by(|a, b| a.file.cmp(&b.file));
            Ok(Json(json!({ "success": true, "source": p.source, "items": items })))
        }
        "bastion" => {
            let proxy = bastion_proxy_url(src)?;
            let remote = src.remote_source.unwrap();
            let client = reqwest::Client::builder()
                .timeout(BASTION_TIMEOUT)
                .build()
                .map_err(|_| AppError::ServiceUnavailable)?;
            let resp = client
                .get(format!("{proxy}/api/record/makecards"))
                .query(&[("source", remote)])
                .send()
                .await
                .map_err(|e| {
                    tracing::warn!("bastion makecards {} 连接失败: {e}", src.id);
                    AppError::ServiceUnavailable
                })?;
            let bytes = resp.bytes().await.map_err(|_| AppError::ServiceUnavailable)?;
            let v: Value = serde_json::from_slice(&bytes).map_err(|_| AppError::ServiceUnavailable)?;
            Ok(Json(v))
        }
        _ => Err(AppError::BadRequest("oss 源无对应服务".into())),
    }
}

#[derive(Deserialize)]
pub struct ActivateReq {
    pub source: String,
    /// 做牌短名 (test_<name>.ini)
    pub name: String,
}

/// `POST /api/record/activate_makecard {source, name}` — 启用做牌:
/// 读 `<服务根>/test_<name>.ini` 全文原位写 `test.ini` (GBK),
/// 返回其 `; Rec=` 关联 (autotest 据此自动加载对应剧本)。覆盖前先备份 test.ini。
pub async fn activate_makecard(Json(req): Json<ActivateReq>) -> Result<Json<Value>> {
    let src = find_source(&req.source).ok_or(AppError::MissingParam("source"))?;
    let name = req.name.trim();
    if name.is_empty() {
        return Err(AppError::MissingParam("name"));
    }
    if name.chars().any(|c| r#"\/:*?"<>|"#.contains(c)) {
        return Err(AppError::BadRequest("名称含非法字符 (\\/:*?\"<>|)".into()));
    }
    match src.kind {
        "local" => {
            let record_dir = std::path::Path::new(local_dir(&req.source).unwrap());
            let svc_root = record_dir.parent().ok_or(AppError::NotFound)?;
            let src_path = svc_root.join(format!("test_{name}.ini"));
            if !src_path.is_file() {
                return Err(AppError::NotFound);
            }
            let bytes = tokio::fs::read(&src_path).await?;
            let text = crate::encoding::decode(&bytes).content;
            let rec = parse_rec_line(&text)
                .map(|(s, id, r)| json!({ "source": s, "record_id": id, "round": r }));
            let target = svc_root.join("test.ini");
            // 覆盖前备份 (test.ini.bak 滚动单份, 不入 .config_history — 非原位写契约面)
            if target.is_file() {
                let _ = tokio::fs::copy(&target, svc_root.join("test.ini.bak")).await;
            }
            tokio::fs::write(&target, &bytes).await?;
            tracing::info!("activate_makecard: {} → {}", src_path.display(), target.display());
            Ok(Json(json!({
                "success": true, "source": req.source, "file": "test.ini",
                "from": format!("test_{name}.ini"), "rec": rec,
            })))
        }
        "bastion" => {
            let proxy = bastion_proxy_url(src)?;
            let remote = src.remote_source.unwrap();
            let client = reqwest::Client::builder()
                .timeout(BASTION_TIMEOUT)
                .build()
                .map_err(|_| AppError::ServiceUnavailable)?;
            let body = serde_json::to_string(&json!({ "source": remote, "name": name }))
                .map_err(|_| AppError::ServiceUnavailable)?;
            let resp = client
                .post(format!("{proxy}/api/record/activate_makecard"))
                .header(reqwest::header::CONTENT_TYPE, "application/json")
                .body(body)
                .send()
                .await
                .map_err(|e| {
                    tracing::warn!("bastion activate_makecard {} 连接失败: {e}", src.id);
                    AppError::ServiceUnavailable
                })?;
            let bytes = resp.bytes().await.map_err(|_| AppError::ServiceUnavailable)?;
            let mut v: Value = serde_json::from_slice(&bytes).map_err(|_| AppError::ServiceUnavailable)?;
            if !v.get("success").and_then(|s| s.as_bool()).unwrap_or(false) {
                return Err(AppError::ServiceUnavailable);
            }
            v["source"] = json!(req.source);
            Ok(Json(v))
        }
        _ => Err(AppError::BadRequest("oss 源无对应服务".into())),
    }
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
    } else {
        // 无日期: spideOnlineLog 无 date 参数返空 []; 传早期 start 单参 → start..today 全范围扫描
        // (首次慢 ~200s+3000项, 进程缓存后续秒返)
        args.push("2020-01-01");
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

// ── 复盘剧本 (record → autotest 回放) ───────────────────────────────────────
//
// GET /api/record/script?source=&id=&round=
// 解析 record 指定局 → 剧本 JSON (供 autotest 客户端逐事件驱动回放):
//   meta { room_id, table_no, players[4], names[4], banker, timestamp }
//   total — RawCards cardid 序列 (test.ini Total 同语义, 引擎发牌确定性复现)
//   actions[] — 逐步动作 (时序): que/exchange/throw/catch/peng/gang{an,mn,pn}/hu
// record 无显式 Guo 事件 — 过为推导量 (决策点非动作椅即过, 终态等价)。
// 事件行格式 (实测):
//   Que <chair> <suit> | Exchange <recv> <from> <cards> | Throw <c> <card>
//   Catch <c> <card> <wallIdx?> | Peng <c> <card> <hand2> | AnGang/MnGang <c> <card> <hand3>
//   PnGang <c> <card> | Hu <c> <card> <fan?> <F?> | Banker <c>

#[derive(Serialize)]
struct ScriptAction {
    /// 时序号 (0 起, 按文件行序)
    seq: usize,
    /// que / exchange / throw / catch / peng / gang / hu / banker
    kind: &'static str,
    /// 动作椅 (exchange = 收牌椅)
    chair: usize,
    /// 牌面 (如 "7T"/"5D"); exchange = 送出牌串; que = 缺门 (W/T/D)
    card: String,
    /// gang 子类: an(暗) / mn(明, 点他人牌) / pn(补杠)
    #[serde(skip_serializing_if = "Option::is_none")]
    gang_type: Option<&'static str>,
    /// exchange: 送牌椅
    #[serde(skip_serializing_if = "Option::is_none")]
    from: Option<usize>,
}

#[derive(Serialize)]
struct RecordScript {
    source: String,
    id: String,
    round: usize,
    /// 局内动作数 (不含 banker 头)
    action_count: usize,
    room_id: String,
    table_no: String,
    players: Vec<String>,
    names: Vec<String>,
    banker: usize,
    timestamp: u64,
    /// RawCards cardid 序列 ("a|b|c", test.ini Total 同语义)
    total: String,
    actions: Vec<ScriptAction>,
}

#[derive(Deserialize)]
pub struct ScriptParams {
    pub source: String,
    pub id: String,
    /// 局序 (0 起, 缺省 0)
    pub round: Option<usize>,
}

/// `GET /api/record/script?source=&id=&round=` — 复盘剧本 (autotest 回放数据源)。
pub async fn script(Query(p): Query<ScriptParams>) -> Result<Json<Value>> {
    if p.source.is_empty() {
        return Err(AppError::MissingParam("source"));
    }
    if p.id.is_empty() {
        return Err(AppError::MissingParam("id"));
    }
    let text = dispatch_get(&p.source, &p.id).await?;
    let sc = parse_script(&text, &p.source, &p.id, p.round.unwrap_or(0))
        .ok_or(AppError::NotFound)?;
    let mut v = serde_json::to_value(&sc).map_err(|_| AppError::ServiceUnavailable)?;
    v["success"] = json!(true);
    Ok(Json(v))
}

/// 从 record 文本解析指定局剧本。局以 `Version ` 行分隔; None = 无该局。
fn parse_script(text: &str, source: &str, id: &str, round: usize) -> Option<RecordScript> {
    // 切局: Version 行界
    let mut rounds: Vec<Vec<&str>> = Vec::new();
    let mut cur: Vec<&str> = Vec::new();
    for line in text.lines() {
        if line.starts_with("Version ") {
            if !cur.is_empty() {
                rounds.push(std::mem::take(&mut cur));
            }
        } else if !line.trim().is_empty() {
            cur.push(line);
        }
    }
    if !cur.is_empty() {
        rounds.push(cur);
    }
    let lines = rounds.get(round)?;

    let mut room_id = String::new();
    let mut table_no = String::new();
    let mut players = vec![String::new(); 4];
    let mut names = vec![String::new(); 4];
    let mut timestamp: u64 = 0;
    let mut banker = 0usize;
    let mut total = String::new();
    let mut actions: Vec<ScriptAction> = Vec::new();

    for line in lines {
        // 事件行 "HH:MM:SS Type Rest..." (时间冒号位 2/5 + 第 9 位空格) → (Type, Rest)
        let (kind, rest) = if line.len() > 9
            && line.as_bytes()[2] == b':'
            && line.as_bytes()[5] == b':'
            && line.as_bytes()[8] == b' '
        {
            let body = &line[9..];
            let mut it = body.splitn(2, ' ');
            (it.next().unwrap_or(""), it.next().unwrap_or("").trim())
        } else if let Some(t) = line.strip_prefix("Timestamp ") {
            timestamp = t.split_whitespace().next().and_then(|s| s.parse().ok()).unwrap_or(0);
            continue;
        } else if let Some(t) = line.strip_prefix("RoomID ") {
            room_id = t.split_whitespace().next().unwrap_or("").to_string();
            continue;
        } else if let Some(t) = line.strip_prefix("TableNO ") {
            table_no = t.split_whitespace().next().unwrap_or("").to_string();
            continue;
        } else if let Some(rest) = line.strip_prefix("ChairNO ") {
            let p: Vec<&str> = rest.split_whitespace().collect();
            if p.len() >= 2 {
                if let Ok(i) = p[0].parse::<usize>() {
                    if i < 4 {
                        players[i] = p[1].to_string();
                    }
                }
            }
            continue;
        } else if let Some(rest) = line.strip_prefix("Name ") {
            let p: Vec<&str> = rest.splitn(2, ' ').collect();
            if p.len() >= 2 {
                if let Ok(i) = p[0].parse::<usize>() {
                    if i < 4 {
                        names[i] = p[1].to_string();
                    }
                }
            }
            continue;
        } else {
            continue;
        };
        // Raw* 双轨跳过 (剧本用牌面轨, Total 用 cardid 轨单独取)
        if kind.starts_with("Raw") {
            if kind == "RawCards" {
                total = rest.split(|c| c == ',' || c == ' ')
                    .filter(|s| !s.is_empty())
                    .collect::<Vec<_>>()
                    .join("|");
            }
            continue;
        }
        let pp: Vec<&str> = rest.split_whitespace().collect();
        let chair = pp.first().and_then(|s| s.parse::<usize>().ok());
        let mut act = |kind: &'static str, chair: usize, card: String| actions.push(ScriptAction {
            seq: actions.len(), kind, chair, card, gang_type: None, from: None,
        });
        match kind {
            "Banker" => {
                if let Some(c) = chair {
                    banker = c;
                }
            }
            "Que" => {
                if let Some(c) = chair {
                    act("que", c, pp.get(1).unwrap_or(&"").to_string());
                }
            }
            "Exchange" => {
                // Exchange <recv> <from> <cards>
                if pp.len() >= 3 {
                    if let (Ok(r), Ok(f)) = (pp[0].parse::<usize>(), pp[1].parse::<usize>()) {
                        actions.push(ScriptAction {
                            seq: actions.len(), kind: "exchange", chair: r,
                            card: pp[2].to_string(), gang_type: None, from: Some(f),
                        });
                    }
                }
            }
            "Throw" => {
                if let Some(c) = chair {
                    act("throw", c, pp.get(1).unwrap_or(&"").to_string());
                }
            }
            "Catch" => {
                if let Some(c) = chair {
                    act("catch", c, pp.get(1).unwrap_or(&"").to_string());
                }
            }
            "Peng" => {
                if let Some(c) = chair {
                    act("peng", c, pp.get(1).unwrap_or(&"").to_string());
                }
            }
            "AnGang" | "MnGang" | "PnGang" => {
                if let Some(c) = chair {
                    let g = match kind {
                        "AnGang" => "an",
                        "MnGang" => "mn",
                        _ => "pn",
                    };
                    actions.push(ScriptAction {
                        seq: actions.len(), kind: "gang", chair: c,
                        card: pp.get(1).unwrap_or(&"").to_string(),
                        gang_type: Some(g), from: None,
                    });
                }
            }
            "Hu" => {
                if let Some(c) = chair {
                    act("hu", c, pp.get(1).unwrap_or(&"").to_string());
                }
            }
            _ => {}
        }
    }
    if actions.is_empty() && total.is_empty() {
        return None;
    }
    Some(RecordScript {
        source: source.to_string(),
        id: id.to_string(),
        round,
        action_count: actions.len(),
        room_id, table_no, players, names, banker, timestamp, total, actions,
    })
}

// ── 局级扫描 (scan_rounds) ──────────────────────────────────────────────────
//
// GET /api/record/scan_rounds?source=&date=
// 下载每个 .log 文件, 扫描每局 header (Version/Timestamp/ChairNO), 返回扁平局列表.
// 每个文件 = 1 个房间, 内含 N 局. 不选房间 = 全部文件的局拼接.

#[derive(Serialize, Clone)]
struct RoundScanMeta {
    file_id: String,
    round_idx: usize,
    room_id: String,
    timestamp: u64,
    players: Vec<String>,
}

/// 局扫描缓存: (source, date) → Vec<RoundScanMeta>
static ROUND_CACHE: LazyLock<RwLock<HashMap<CacheKey, Vec<RoundScanMeta>>>> =
    LazyLock::new(|| RwLock::new(HashMap::new()));

#[derive(Deserialize)]
pub struct ScanParams {
    pub source: String,
    pub date: Option<String>,
}

/// `GET /api/record/scan_rounds?source=&date=` — 局级扫描 (下载文件 + 扫 header).
pub async fn scan_rounds(Query(p): Query<ScanParams>) -> Result<Json<Value>> {
    if p.source.is_empty() { return Err(AppError::MissingParam("source")); }
    find_source(&p.source).ok_or(AppError::MissingParam("source"))?;
    let date = p.date.clone().unwrap_or_default();
    let key = (p.source.clone(), date.clone());

    // 缓存命中
    {
        let cache = ROUND_CACHE.read().await;
        if let Some(rounds) = cache.get(&key) {
            return Ok(Json(json!({ "success": true, "source": key.0, "date": key.1, "rounds": rounds, "cached": true })));
        }
    }

    // 拉文件列表
    let items = dispatch_list(&p.source, &date).await?;
    tracing::info!("scan_rounds: {} files to scan for source={}", items.len(), p.source);

    // 逐文件下载 + 扫描
    let mut all_rounds = Vec::new();
    for item in &items {
        let text = match dispatch_get(&p.source, &item.id).await {
            Ok(t) => t,
            Err(e) => { tracing::warn!("scan_rounds: skip {} (get failed: {})", item.id, e); continue; }
        };
        let rounds = scan_rounds_in_text(&text, &item.id);
        tracing::info!("scan_rounds: {} → {} rounds", item.id, rounds.len());
        all_rounds.extend(rounds);
    }
    tracing::info!("scan_rounds: total {} rounds", all_rounds.len());

    ROUND_CACHE.write().await.insert(key.clone(), all_rounds.clone());
    Ok(Json(json!({ "success": true, "source": key.0, "date": key.1, "rounds": all_rounds, "cached": false })))
}

/// 从 record 文本扫描每局 header → 扁平局列表.
/// 每个 `Version` 行标记新一局, 收集后续 Timestamp/RoomID/ChairNO.
fn scan_rounds_in_text(text: &str, file_id: &str) -> Vec<RoundScanMeta> {
    let mut rounds = Vec::new();
    let mut idx = 0usize;
    let mut ts: u64 = 0;
    let mut room = String::new();
    let mut players = vec![String::new(); 4];
    let mut chairno_count = 0u8;

    for line in text.lines() {
        if line.starts_with("Version ") {
            if chairno_count > 0 {
                rounds.push(RoundScanMeta {
                    file_id: file_id.to_string(), round_idx: idx,
                    room_id: room.clone(), timestamp: ts, players: players.clone(),
                });
                idx += 1;
            }
            players = vec![String::new(); 4];
            chairno_count = 0;
        } else if let Some(v) = line.strip_prefix("Timestamp ") {
            ts = v.split_whitespace().next().and_then(|s| s.parse().ok()).unwrap_or(0);
        } else if let Some(v) = line.strip_prefix("RoomID ") {
            room = v.split_whitespace().next().unwrap_or("").to_string();
        } else if let Some(rest) = line.strip_prefix("ChairNO ") {
            let parts: Vec<&str> = rest.split_whitespace().collect();
            if parts.len() >= 2 {
                if let Ok(i) = parts[0].parse::<usize>() {
                    if i < 4 { players[i] = parts[1].to_string(); chairno_count += 1; }
                }
            }
        }
    }
    if chairno_count > 0 {
        rounds.push(RoundScanMeta {
            file_id: file_id.to_string(), round_idx: idx,
            room_id: room, timestamp: ts, players,
        });
    }
    rounds
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
        assert_eq!(local_dir("local-xzmo"), Some(r"D:\game\xzmo\server_game\Record"));
        assert_eq!(local_dir("local-xzmo2"), Some(r"D:\game\xzmo2\server_game\Record"));
        assert_eq!(local_dir("oss-xzms-3291"), None);
    }

    #[test]
    fn sources_table_sanity() {
        // 3 local + 4 oss-xzms + 4 oss-xzmo + 6 bastion = 17
        assert_eq!(SOURCES.len(), 17, "源清单数量");
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

    #[test]
    fn parse_script_extracts_actions() {
        let txt = "Version 1.1\r\n\
Timestamp 1788156823\r\nRoomID 11783\r\nTableNO 1\r\n\
ChairNO 0 1040720 256 -1\r\nChairNO 1 1040723 256 -1\r\n\
Name 0 甲\r\nName 1 乙\r\n\
00:00:01 Banker 0\r\n\
00:00:02 RawCards 0,9,18,27\r\n\
00:00:03 Que 0 D\r\n\
00:00:04 Exchange 0 1 9T5T3T\r\n\
00:00:05 Throw 0 3T\r\n\
00:00:06 Catch 1 4T 53\r\n\
00:00:07 Peng 2 3T 3T3T\r\n\
00:00:08 AnGang 0 1W 1W1W1W\r\n\
00:00:09 MnGang 3 5D 5D5D5D\r\n\
00:00:10 PnGang 1 6D\r\n\
00:00:11 Hu 2 6T 1 F\r\n\
Version 1.1\r\n\
Timestamp 1788157000\r\nRoomID 11783\r\nTableNO 1\r\n\
ChairNO 0 1040720 256 -1\r\n\
00:00:01 Throw 0 9W\r\n";
        let sc = parse_script(txt, "local-xzmo2", "11783_20260831.log", 0).unwrap();
        assert_eq!(sc.room_id, "11783");
        assert_eq!(sc.banker, 0);
        assert_eq!(sc.total, "0|9|18|27");
        assert_eq!(sc.players[0], "1040720");
        assert_eq!(sc.actions.len(), 9);
        let a = &sc.actions;
        assert_eq!((a[0].kind, a[0].chair, a[0].card.as_str()), ("que", 0, "D"));
        assert_eq!((a[1].kind, a[1].chair, a[1].from), ("exchange", 0, Some(1)));
        assert_eq!(a[1].card, "9T5T3T");
        assert_eq!((a[2].kind, a[2].chair, a[2].card.as_str()), ("throw", 0, "3T"));
        assert_eq!((a[3].kind, a[3].chair, a[3].card.as_str()), ("catch", 1, "4T"));
        assert_eq!((a[4].kind, a[4].chair, a[4].card.as_str()), ("peng", 2, "3T"));
        assert_eq!((a[5].kind, a[5].gang_type), ("gang", Some("an")));
        assert_eq!((a[6].kind, a[6].gang_type), ("gang", Some("mn")));
        assert_eq!((a[7].kind, a[7].gang_type), ("gang", Some("pn")));
        assert_eq!((a[8].kind, a[8].chair, a[8].card.as_str()), ("hu", 2, "6T"));
        // round 越界 → None; round 1 只剩 Throw
        assert!(parse_script(txt, "s", "i", 5).is_none());
        let sc2 = parse_script(txt, "s", "i", 1).unwrap();
        assert_eq!(sc2.actions.len(), 1);
        assert_eq!(sc2.timestamp, 1788157000);
    }
}
