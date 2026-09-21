//! 服务目录文件管理 (规格: `serviceserver_spec/09_文件管理.md`)。
//!
//! 端点:
//! - `POST /api/files/upload?serviceId=&relPath=` (multipart) — 新建 / 覆盖, 父目录自动建
//! - `POST /api/files/delete   {serviceId, relPath}` — **先备份再删** (只删文件, 不递归目录)
//! - `GET  /api/files/backups?serviceId=&relPath=` — 列该文件的备份 (纳秒时间戳倒序)
//! - `POST /api/files/restore  {serviceId, relPath, backupName?}` — 从备份还原 (缺省最新)
//! - `GET  /api/files/recycle?serviceId=` — 整服务的回收站 (跨文件, 含已删除文件)
//!
//! 五条红线:
//! 1. 只收**相对路径** (`relPath`): 拒盘符 / 绝对路径 / `..` 逃逸;
//! 2. **拒 `.exe`**: 运行中镜像被锁, 且换代本有部署包 / update 专用通道;
//! 3. **拒保留区**: 路径任一层级为 `.config_history` / `remove` —— 否则「可恢复」是假的;
//! 4. 只收**文件**不收目录 (delete 遇目录拒; upload 目标是目录拒);
//! 5. 沙箱 = 「各服务自己的目录」(`path_map.valid_roots`, 分量比较非 startswith)。
//!
//! 写策略: 覆盖 / 删除前一律 `rotate_backup` (这就是回收站的来源); 配置类扩展名
//! (ini/json/lua) 走 `write_in_place_bytes` 保下游 assistB `FILE_ACTION_MODIFIED`
//! 事件契约, 其余扩展名普通写。

use crate::atomic_write::write_in_place_bytes;
use crate::backup::{list_backups, rotate_backup};
use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::extract::{Multipart, Query, State};
use axum::Json;
use serde::{Deserialize, Serialize};
use std::path::{Component, Path, PathBuf};

/// 保留区目录名 (任一层级命中即拒): 备份本体与分支切换暂存区。
const RESERVED_DIRS: &[&str] = &[".config_history", "remove"];
/// 配置文件扩展名: 沿用原位写 (保 MODIFIED 事件契约), 其余走普通写。
const CONFIG_EXTS: &[&str] = &["ini", "json", "lua"];
/// 回收站根目录名 (与 `backup.rs` 的 HISTORY_DIR_NAME 同源)。
const HISTORY_DIR_NAME: &str = ".config_history";

// ============================ 校验 (红线) ============================

/// relPath 红线: 非空、纯相对、无 `..` 逃逸、不落保留区。
fn assert_rel_safe(rel: &Path) -> Result<()> {
    if rel.as_os_str().is_empty() {
        return Err(AppError::MissingParam("relPath"));
    }
    for comp in rel.components() {
        match comp {
            // 盘符 (D:) 与根 (:\) —— 只收相对路径。
            Component::Prefix(_) | Component::RootDir => return Err(AppError::Forbidden),
            // `..` 一律拒 (即便规范化后仍在根内, 也视为越权尝试)。
            Component::ParentDir => return Err(AppError::Forbidden),
            Component::Normal(name) => {
                let n = name.to_string_lossy();
                if RESERVED_DIRS.iter().any(|r| n.eq_ignore_ascii_case(r)) {
                    return Err(AppError::BadRequest(format!(
                        "'{n}' 是保留区 (备份/分支暂存), 禁写禁删; 备份只能经「回收站」还原"
                    )));
                }
            }
            Component::CurDir => {}
        }
    }
    Ok(())
}

/// `.exe` 红线: 上传与删除都拒 (指路部署通道 / update 端点)。
fn assert_ext_not_exe(target: &Path) -> Result<()> {
    let ext = target
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();
    if ext == "exe" {
        return Err(AppError::BadRequest(
            "exe 不能经此上传或删除: 运行中镜像被锁, 换代请走部署包通道 (:5099 /api/deploy) 或 update 端点".into(),
        ));
    }
    Ok(())
}

fn file_name_str(p: &Path) -> String {
    p.file_name()
        .and_then(|n| n.to_str())
        .unwrap_or_default()
        .to_string()
}

/// 是否配置文件扩展名 (决定原位写还是普通写)。
fn is_config_ext(p: &Path) -> bool {
    let ext = p
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();
    CONFIG_EXTS.iter().any(|a| *a == ext)
}

/// 备份名 → (原文件名, 纳秒时间戳)。
///
/// 命名来自 `backup.rs`: `format!("{file_name}.{nanos:020}")`, 故**最后一个点**之后
/// 即时间戳; 原文件名本身可含点 (如 `xzmoSvr.ini.0178999...` → `xzmoSvr.ini`)。
/// 解析不出时间戳 (非本系统生成的残留) 返回 None, 排序时退化按名字比较。
fn split_backup_name(name: &str) -> Option<(&str, u128)> {
    let idx = name.rfind('.')?;
    let (orig, ts) = name.split_at(idx);
    let nanos = ts.get(1..)?.parse::<u128>().ok()?;
    if orig.is_empty() {
        return None;
    }
    Some((orig, nanos))
}

/// 把备份写入目标: 配置类扩展名走原位写 (触发 MODIFIED 契约), 其余普通写。
/// 两者对**不存在的文件**都能创建 (`fs::write` 语义)。
fn write_target(target: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)?;
    }
    if is_config_ext(target) {
        write_in_place_bytes(target, bytes)
    } else {
        std::fs::write(target, bytes).map_err(AppError::Io)
    }
}

// ============================ 定位 ============================

/// serviceId → 服务根 (含存在性校验)。
///
/// 工具自身 (`service-server_self`) 不在 `config.json` 服务表里, `path_map` 必然
/// 未命中 → 报服务不存在。这是有意的: 首刀决策限定工具自身只给「重启自身 + 配置编辑」,
/// 不开放文件上传/删除 (否则可删掉自己的源码/配置)。
fn resolve_service(state: &AppState, service_id: &str) -> Result<crate::path_map::ServicePath> {
    state.path_map.refresh(&state.config_path)?;
    let svc = state
        .path_map
        .get(service_id)
        .ok_or_else(|| AppError::ServiceNotFound(service_id.to_string()))?;
    if !svc.path.exists() {
        return Err(AppError::ServiceUnavailable);
    }
    Ok(svc)
}

/// serviceId + relPath → 绝对目标路径 (过五条红线中的前三条)。
fn resolve_target(state: &AppState, service_id: &str, rel_path: &str) -> Result<PathBuf> {
    let svc = resolve_service(state, service_id)?;
    let rel = Path::new(rel_path);
    assert_rel_safe(rel)?;
    let target = svc.path.join(rel);
    assert_ext_not_exe(&target)?;
    Ok(target)
}

// ============================ 端点 ============================

#[derive(Deserialize)]
pub struct UploadParams {
    #[serde(rename = "serviceId")]
    pub service_id: String,
    #[serde(rename = "relPath")]
    pub rel_path: String,
}

#[derive(Serialize)]
pub struct UploadResp {
    pub success: bool,
    pub message: String,
    pub path: String,
    /// 覆盖既有文件时回带备份路径 (新建为空)。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub backup_path: Option<String>,
}

/// POST /api/files/upload?serviceId=&relPath= (multipart)
///
/// 取 multipart 里第一个带文件名的字段 (不限字段名, 兼容前端 `file`)。
/// 目标已存在 → 先滚动备份再原位写; 不存在 → 父目录自动创建后直接写。
pub async fn upload_file(
    State(state): State<AppState>,
    Query(params): Query<UploadParams>,
    mut multipart: Multipart,
) -> Result<Json<UploadResp>> {
    let target = resolve_target(&state, &params.service_id, &params.rel_path)?;

    if target.is_dir() {
        return Err(AppError::BadRequest("目标已是目录, 只支持上传文件".into()));
    }

    let mut payload: Option<Vec<u8>> = None;
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| AppError::BadRequest(format!("multipart 解析失败: {e}")))?
    {
        if field.file_name().is_some() || field.name() == Some("file") {
            let bytes = field
                .bytes()
                .await
                .map_err(|e| AppError::BadRequest(format!("读取上传内容失败: {e}")))?;
            payload = Some(bytes.to_vec());
            break;
        }
    }
    let bytes = payload.ok_or_else(|| AppError::BadRequest("multipart 缺少文件字段".into()))?;

    // 覆盖前先备份 (回收站来源); 新建无备份。
    let backup_path = if target.is_file() {
        Some(rotate_backup(&target)?.display().to_string())
    } else {
        None
    };
    let size = bytes.len();
    write_target(&target, &bytes)?;

    Ok(Json(UploadResp {
        success: true,
        message: if backup_path.is_some() {
            format!("已覆盖 ({} 字节), 原文件已进回收站", size)
        } else {
            format!("已上传 ({} 字节)", size)
        },
        path: target.display().to_string(),
        backup_path,
    }))
}

#[derive(Deserialize)]
pub struct DeleteReq {
    #[serde(rename = "serviceId")]
    pub service_id: String,
    #[serde(rename = "relPath")]
    pub rel_path: String,
}

#[derive(Serialize)]
pub struct DeleteResp {
    pub success: bool,
    pub message: String,
    /// 删除前落的备份路径 (回收站入口)。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub backup_path: Option<String>,
}

/// POST /api/files/delete {serviceId, relPath}
///
/// 回收站语义: **先滚动备份, 再删除**。不递归删目录。
pub async fn delete_file(
    State(state): State<AppState>,
    Json(req): Json<DeleteReq>,
) -> Result<Json<DeleteResp>> {
    let target = resolve_target(&state, &req.service_id, &req.rel_path)?;

    if target.is_dir() {
        return Err(AppError::BadRequest(
            "只支持删除文件, 不支持目录 (防误删整棵子树)".into(),
        ));
    }
    if !target.is_file() {
        return Err(AppError::NotFound);
    }

    let backup = rotate_backup(&target)?;
    std::fs::remove_file(&target)?;

    Ok(Json(DeleteResp {
        success: true,
        message: format!(
            "已删除 '{}', 可在「回收站」还原",
            file_name_str(&target)
        ),
        backup_path: Some(backup.display().to_string()),
    }))
}

#[derive(Deserialize)]
pub struct BackupsParams {
    #[serde(rename = "serviceId")]
    pub service_id: String,
    #[serde(rename = "relPath")]
    pub rel_path: String,
}

#[derive(Serialize)]
pub struct BackupEntry {
    pub name: String,
    pub size: u64,
    pub backup_path: String,
}

#[derive(Serialize)]
pub struct BackupsResp {
    pub success: bool,
    pub path: String,
    /// 纳秒时间戳倒序 (最新在前); 无备份即空数组 (目标文件不存在也返空, 不报错)。
    pub backups: Vec<BackupEntry>,
}

/// GET /api/files/backups?serviceId=&relPath= — 列该文件的备份。
pub async fn list_file_backups(
    State(state): State<AppState>,
    Query(params): Query<BackupsParams>,
) -> Result<Json<BackupsResp>> {
    let target = resolve_target(&state, &params.service_id, &params.rel_path)?;

    let backups = list_backups(&target)?;
    let entries = backups
        .iter()
        .map(|b| BackupEntry {
            name: file_name_str(b),
            size: std::fs::metadata(b).map(|m| m.len()).unwrap_or(0),
            backup_path: b.display().to_string(),
        })
        .collect();

    Ok(Json(BackupsResp {
        success: true,
        path: target.display().to_string(),
        backups: entries,
    }))
}

#[derive(Deserialize)]
pub struct RestoreReq {
    #[serde(rename = "serviceId")]
    pub service_id: String,
    #[serde(rename = "relPath")]
    pub rel_path: String,
    /// 指定备份名 (只取其中文件名部分, 防借备份名穿越); 缺省取最新一份。
    #[serde(rename = "backupName", default)]
    pub backup_name: Option<String>,
}

#[derive(Serialize)]
pub struct RestoreResp {
    pub success: bool,
    pub message: String,
    pub bytes: u64,
    pub from_backup: String,
}

/// POST /api/files/restore {serviceId, relPath, backupName?}
///
/// 还原前把**当前文件也滚一份** —— 让还原动作本身可反悔 (否则还原即丢现状)。
/// 目标文件已被删除时直接重建 (无当前文件可备份)。
pub async fn restore_file(
    State(state): State<AppState>,
    Json(req): Json<RestoreReq>,
) -> Result<Json<RestoreResp>> {
    let target = resolve_target(&state, &req.service_id, &req.rel_path)?;

    let backups = list_backups(&target)?;
    let source = match req.backup_name.as_deref() {
        // 只取备份名的**文件名部分**: 传 `..\\..\\x` 也只当 `x` 处理。
        Some(raw) => {
            let wanted = Path::new(raw)
                .file_name()
                .and_then(|n| n.to_str())
                .ok_or(AppError::NotFound)?
                .to_string();
            backups
                .iter()
                .find(|p| file_name_str(p) == wanted)
                .cloned()
                .ok_or(AppError::NotFound)?
        }
        None => backups.into_iter().next().ok_or(AppError::NotFound)?,
    };

    if !source.is_file() {
        return Err(AppError::NotFound);
    }
    let bytes = std::fs::read(&source)?;

    // 当前文件也在则先滚一份 (还原本身可反悔); 已删除则跳过。
    if target.is_file() {
        rotate_backup(&target)?;
    }
    write_target(&target, &bytes)?;

    Ok(Json(RestoreResp {
        success: true,
        message: format!(
            "已还原 '{}' ({} 字节)",
            file_name_str(&target),
            bytes.len()
        ),
        bytes: bytes.len() as u64,
        from_backup: file_name_str(&source),
    }))
}

#[derive(Deserialize)]
pub struct RecycleParams {
    #[serde(rename = "serviceId")]
    pub service_id: String,
}

#[derive(Serialize)]
pub struct RecycleEntry {
    /// 原文件相对服务根的路径 = 还原时回填的 `relPath`。
    pub rel_path: String,
    /// 原文件名 (回收站里显示的主行)。
    pub original: String,
    /// 备份名 (`<原文件名>.<纳秒时间戳>`)。
    pub name: String,
    pub size: u64,
    pub backup_path: String,
}

#[derive(Serialize)]
pub struct RecycleResp {
    pub success: bool,
    pub entries: Vec<RecycleEntry>,
}

/// GET /api/files/recycle?serviceId= — 整服务的回收站 (跨文件)。
///
/// 与 `backups` 的区别: 那个要 `relPath`, 只能查到**还存在**的文件; 前端要「还原被
/// 删除的文件」时文件已不在列表里, 故这里直接摊平服务根的 `.config_history/<原文件名>/`。
///
/// 范围边界: 只扫**服务根一层**的 `.config_history` (与配置编辑页只列根层文件同口径);
/// 子目录里的历史备份不在本列表内。
pub async fn list_recycle(
    State(state): State<AppState>,
    Query(params): Query<RecycleParams>,
) -> Result<Json<RecycleResp>> {
    let svc = resolve_service(&state, &params.service_id)?;

    let history_root = svc.path.join(HISTORY_DIR_NAME);
    let mut entries: Vec<RecycleEntry> = Vec::new();

    if history_root.is_dir() {
        for dir in std::fs::read_dir(&history_root)?.filter_map(|e| e.ok()) {
            let dir_path = dir.path();
            if !dir_path.is_dir() {
                continue;
            }
            // 目录名 = 原文件名 (backup.rs: history_dir_for)。
            let original = match dir_path.file_name().and_then(|n| n.to_str()) {
                Some(n) => n.to_string(),
                None => continue,
            };
            for f in std::fs::read_dir(&dir_path)?.filter_map(|e| e.ok()) {
                let path = f.path();
                if !path.is_file() {
                    continue;
                }
                entries.push(RecycleEntry {
                    rel_path: original.clone(),
                    original: original.clone(),
                    name: file_name_str(&path),
                    size: std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0),
                    backup_path: path.display().to_string(),
                });
            }
        }
    }

    // 最新在前: 纳秒时间戳降序, 解析不出的退化按名字降序 (稳定且确定)。
    entries.sort_by(|a, b| {
        let ka = split_backup_name(&a.name).map(|(_, t)| t);
        let kb = split_backup_name(&b.name).map(|(_, t)| t);
        kb.cmp(&ka).then_with(|| b.name.cmp(&a.name))
    });

    Ok(Json(RecycleResp {
        success: true,
        entries,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    #[test]
    fn test_file_name_str_extracts_basename() {
        assert_eq!(file_name_str(Path::new("D:/game/x/cfg.ini")), "cfg.ini");
        assert_eq!(file_name_str(Path::new("cfg.ini")), "cfg.ini");
    }

    #[rstest]
    #[case("", false, "空路径")]
    #[case("cfg.ini", true, "根层文件")]
    #[case("./cfg.ini", true, "当前目录前缀可接受")]
    #[case("sub/cfg.ini", true, "子目录文件")]
    fn test_assert_rel_safe_accepts_relative(#[case] rel: &str, #[case] ok: bool, #[case] why: &str) {
        assert_eq!(assert_rel_safe(Path::new(rel)).is_ok(), ok, "{why}");
    }

    /// 红线矩阵: 盘符 / 绝对 / `..` 逃逸 / 保留区 一律拒。
    #[rstest]
    #[case("D:/game/x/cfg.ini", "盘符绝对路径")]
    #[case("/etc/passwd", "根路径")]
    #[case("../cfg.ini", "父目录逃逸")]
    #[case("sub/../../cfg.ini", "规范化后仍越权, 也拒")]
    #[case(".config_history/x/cfg.ini", "保留区 (备份本体)")]
    #[case("sub/.config_history/x", "保留区在深层")]
    #[case("remove/cfg.ini", "保留区 (分支暂存)")]
    #[case("sub/remove/cfg.ini", "保留区在深层")]
    #[case(".CONFIG_HISTORY/x", "保留区大小写不敏感")]
    fn test_assert_rel_safe_rejects_red_lines(#[case] rel: &str, #[case] why: &str) {
        assert!(assert_rel_safe(Path::new(rel)).is_err(), "{why} 必须被拒");
    }

    /// `.exe` 红线: 大小写不敏感; 含 exe 字样的其它扩展名照收。
    #[rstest]
    #[case("xzmoSvr.exe", false, ".exe 拒")]
    #[case("XZMO.EXE", false, "大写 .EXE 拒")]
    #[case("cfg.ini", true, "ini 收")]
    #[case("aexe", true, "无扩展名且非 .exe 收")]
    #[case("note.exe.txt", true, "末段扩展名才是判据")]
    fn test_assert_ext_not_exe(#[case] name: &str, #[case] ok: bool, #[case] why: &str) {
        assert_eq!(assert_ext_not_exe(Path::new(name)).is_ok(), ok, "{why}");
    }

    #[rstest]
    #[case("cfg.ini", true, "配置文件走原位写")]
    #[case("goods.json", true, "json 走原位写")]
    #[case("logic.lua", true, "lua 走原位写")]
    #[case("readme.txt", false, "其它普通写")]
    #[case("noext", false, "无扩展名普通写")]
    fn test_is_config_ext(#[case] name: &str, #[case] expected: bool, #[case] why: &str) {
        assert_eq!(is_config_ext(Path::new(name)), expected, "{why}");
    }

    /// 备份名解析: 原文件名可含点, 只在**最后一个点**切开。
    #[rstest]
    #[case("xzmoSvr.ini.01789995852048462300", Some(("xzmoSvr.ini", 1789995852048462300)))]
    #[case("a.b.c.00000000000000000001", Some(("a.b.c", 1)))]
    #[case("noext", None)]
    #[case("cfg.ini", None)]
    #[case(".12345678901234567890", None)]
    fn test_split_backup_name(#[case] name: &str, #[case] expected: Option<(&str, u128)>) {
        assert_eq!(split_backup_name(name), expected);
    }
}
