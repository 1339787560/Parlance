//! GET /api/services/status + GET /api/config/services/running
//!
//! status 走 TTL 缓存 (status_cache), 命中不重复 SCM syscall。running 端点
//! 额外过滤 configHide (配置编辑页不展示隐藏服务)。
//!
//! ports 字段 (Win32 only): 单次请求内一次性 snapshot 全进程 + IP Helper
//! 聚合 LISTEN 端口, 避免每服务 N 次 syscall (legacy psutil iter 慢源)。

use crate::error::{AppError, Result};
use crate::ports_probe::PortsProbe;
use crate::state::AppState;
use axum::extract::{Multipart, State};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::PathBuf;

/// GET /api/services/status — 全服务状态。
pub async fn list_status(State(state): State<AppState>) -> Result<Json<serde_json::Value>> {
    state.path_map.refresh(&state.config_path)?;
    let services = state.path_map.all();
    let provider = state.status_provider.as_ref();
    // ports 探测集合 (Win32 一次 snapshot + IP Helper; 非 windows 走 stub 空)。
    let ports_probe = PortsProbe::capture();
    let mut map = BTreeMap::new();
    for svc in services {
        let st = state
            .status_cache
            .get_or_query(&svc.service_id, provider);
        // shape 对齐 legacy Service.py get_all_service_status:
        //   status / type / exe / name / display_name / path / exe_path / ports
        let display_name = format!("同城游_{}_{}", svc.name, svc.svc_type);
        let exe_path = svc.path.join(&svc.exe);
        let ports = ports_str(st, &exe_path, &svc.exe, &ports_probe);
        map.insert(
            svc.service_id.clone(),
            serde_json::json!({
                "status": st.label(),
                "type": svc.svc_type,
                "exe": svc.exe,
                "name": svc.name,
                "display_name": display_name,
                "path": svc.path.display().to_string(),
                "exe_path": exe_path.display().to_string(),
                "ports": ports,
            }),
        );
    }
    Ok(Json(serde_json::to_value(map).unwrap()))
}

/// 按 status 语义决定 ports 字段串, 对齐 legacy Service.py 各分支。
/// - Running -> 查 pid 监听端口 CSV (空则 "未监听")
/// - Stopped -> "未运行"
/// - NotFound / QueryFailed -> "未部署" (legacy 把 QueryServiceStatus 抛错归为未部署)
fn ports_str(
    st: crate::status::ServiceState,
    exe_path: &std::path::Path,
    exe: &str,
    probe: &PortsProbe,
) -> String {
    use crate::status::ServiceState::*;
    match st {
        Running => match probe.find_pid(exe, exe_path) {
            Some(pid) => {
                let ports = probe.ports_for_pid(pid);
                crate::ports_probe::format_ports_csv(&ports)
            }
            None => "未监听".to_string(),
        },
        Stopped => "未运行".to_string(),
        NotFound | QueryFailed => "未部署".to_string(),
    }
}

/// GET /api/config/services/running — 仅运行中服务 (configHide 过滤), 供配置编辑页。
pub async fn running_services(State(state): State<AppState>) -> Result<Json<serde_json::Value>> {
    state.path_map.refresh(&state.config_path)?;
    let services = state.path_map.all();
    let mut map = BTreeMap::new();
    for svc in services {
        if state.path_map.is_hidden(&svc.name, &svc.svc_type) {
            continue;
        }
        let st = state
            .status_cache
            .get_or_query(&svc.service_id, state.status_provider.as_ref());
        if !st.is_running() {
            continue;
        }
        let display_name = format!("{} {}", svc.name, svc.exe);
        map.insert(
            svc.service_id.clone(),
            serde_json::json!({
                "name": display_name,
                "original_name": svc.name,
                "exe": svc.exe,
                "exe_name": svc.exe,
                "type": svc.svc_type,
                "path": svc.path.display().to_string(),
                "status": st.label(),
            }),
        );
    }
    Ok(Json(serde_json::to_value(map).unwrap()))
}

// ---- 控制: start / stop / restart / delete ----
//
// shape 对齐 legacy CustomRoute/ServiceRoute.py:
//   start {name,type,exe} -> {success,message} 异步 (立即返 "请求已提交")
//   stop  {name,type,exe} -> {success,message} 同步
//   restart {name,type,exe} -> {success,message} 异步
//   delete {name,type} -> {success,message} 同步
// service_name = "{name}_{type}" (Windows SCM 注册名)。

#[derive(Deserialize)]
pub struct ServiceReq {
    pub name: String,
    #[serde(rename = "type")]
    pub svc_type: String,
    pub exe: Option<String>,
}

impl ServiceReq {
    fn service_id(&self) -> String {
        format!("{}_{}", self.name, self.svc_type)
    }
}

/// POST /api/services/start — 异步: tokio task spawn_blocking 跑 SCM start,
/// 立即返 "请求已提交", 完成后 invalidate status_cache。
pub async fn start_service(
    State(state): State<AppState>,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    if req.exe.is_none() {
        return Ok(Json(json_err(400, "参数不完整")));
    }
    let id = req.service_id();
    let cache = state.status_cache.clone();
    let id_task = id.clone();
    tokio::task::spawn_blocking(move || {
        let _ = crate::svc_control::imp::start(&id_task);
        cache.invalidate(&id_task);
    });
    Ok(Json(serde_json::json!({
        "success": true,
        "message": "服务启动请求已提交",
    })))
}

/// POST /api/services/stop — 同步: ControlService STOP + 轮询 STOPPED (10s)。
pub async fn stop_service(
    State(state): State<AppState>,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    if req.exe.is_none() {
        return Ok(Json(json_err(400, "请提供可执行文件名")));
    }
    let id = req.service_id();
    let res = tokio::task::spawn_blocking(move || crate::svc_control::imp::stop(&id))
        .await
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
    state.status_cache.invalidate(&req.service_id());
    match res {
        Ok(msg) => Ok(Json(serde_json::json!({ "success": true, "message": msg }))),
        Err(msg) => Ok(Json(serde_json::json!({ "success": false, "message": msg }))),
    }
}

/// POST /api/services/restart — 异步: stop -> sleep 2s -> start, 立即返。
pub async fn restart_service(
    State(state): State<AppState>,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    if req.exe.is_none() {
        return Ok(Json(json_err(400, "参数不完整（需要 name, type, exe）")));
    }
    let id = req.service_id();
    let cache = state.status_cache.clone();
    let id_task = id.clone();
    tokio::task::spawn_blocking(move || {
        let _ = crate::svc_control::imp::stop(&id_task);
        std::thread::sleep(std::time::Duration::from_secs(2));
        let _ = crate::svc_control::imp::start(&id_task);
        cache.invalidate(&id_task);
    });
    Ok(Json(serde_json::json!({
        "success": true,
        "message": "服务重启请求已提交（停止 → 等待 → 启动）",
    })))
}

/// POST /api/services/delete — 同步: DeleteService (SCM 注销)。
pub async fn delete_service(
    State(state): State<AppState>,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    let id = req.service_id();
    let res = tokio::task::spawn_blocking(move || crate::svc_control::imp::delete(&id))
        .await
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
    state.status_cache.invalidate(&req.service_id());
    match res {
        Ok(msg) => Ok(Json(serde_json::json!({ "success": true, "message": msg }))),
        Err(msg) => Ok(Json(serde_json::json!({ "success": false, "message": msg }))),
    }
}

fn json_err(code: u16, msg: &str) -> serde_json::Value {
    serde_json::json!({ "success": false, "message": msg, "_status": code })
}

// ---- deploy / start-all / update ----
//
// 对齐 legacy CustomRoute/ServiceRoute.py:
//   deploy    {name,type,exe} -> 校验 exe 存在 + config 加条目 + sc create, 返 {success,message}
//   start-all (无 body) -> 后台按序启动, 立即返 "所有服务已开始启动"
//   update    multipart(name/type/exe + file_exe/file_pdb) -> 停 -> 替换 -> 启, 同步返

/// POST /api/services/deploy — 部署服务。
pub async fn deploy_service(
    State(state): State<AppState>,
    Json(req): Json<ServiceReq>,
) -> Result<(StatusCode, Json<Value>)> {
    let exe = match &req.exe {
        Some(e) if !e.is_empty() => e.clone(),
        _ => {
            return Ok((
                StatusCode::BAD_REQUEST,
                Json(json!({ "success": false, "message": "参数不完整" })),
            ))
        }
    };
    state.path_map.refresh(&state.config_path)?;
    let abspath = state.path_map.abspath();
    let service_path = exe_path(&abspath, &req.name, &req.svc_type, &exe);
    if !service_path.exists() {
        return Ok((
            StatusCode::OK,
            Json(json!({
                "success": false,
                "message": format!("服务文件不存在: {}", service_path.display())
            })),
        ));
    }
    // 配置加条目 (type 已存在则跳过, 对齐 legacy 逻辑), 变更才回写。
    let mut config = crate::routes::read_config_value(&state.config_path)?;
    if ensure_service_entry(&mut config, &req.name, &req.svc_type, &exe) {
        crate::routes::write_config_value(&state.config_path, &config)?;
    }
    // sc create 注册 Windows 服务 (对齐 legacy os.popen('sc create ...'))。
    let service_name = req.service_id();
    let display = display(&service_name);
    let registered = sc_create(&service_name, &service_path.display().to_string(), &display);
    let message = if registered {
        format!("服务 {display} 已成功部署到 {}，并已注册为Windows服务", req.name)
    } else {
        format!("服务 {display} 已成功部署到 {}（配置已添加，但未注册为Windows服务）", req.name)
    };
    Ok((StatusCode::OK, Json(json!({ "success": true, "message": message }))))
}

/// POST /api/services/start-all — 后台按序启动, 立即返 (对齐 legacy daemon thread)。
pub async fn start_all_services(State(state): State<AppState>) -> Result<(StatusCode, Json<Value>)> {
    let config_path = state.config_path.clone();
    let path_map = state.path_map.clone();
    tokio::task::spawn_blocking(move || {
        if let Err(e) = run_start_all(&config_path, &path_map) {
            tracing::warn!("start-all 执行失败: {e}");
        }
    });
    Ok((
        StatusCode::OK,
        Json(json!({ "success": true, "message": "所有服务已开始启动，请稍后查看状态" })),
    ))
}

/// POST /api/services/update — multipart 上传 exe/pdb 热更新 (停 -> 替换 -> 启)。
pub async fn update_service(
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> Result<(StatusCode, Json<Value>)> {
    let mut name: Option<String> = None;
    let mut svc_type: Option<String> = None;
    let mut exe: Option<String> = None;
    let mut file_exe: Option<(String, Vec<u8>)> = None;
    let mut file_pdb: Option<(String, Vec<u8>)> = None;

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?
    {
        let field_name = field.name().unwrap_or("").to_string();
        match field_name.as_str() {
            "name" => name = Some(field.text().await.map_err(mp_err)?),
            "type" => svc_type = Some(field.text().await.map_err(mp_err)?),
            "exe" => exe = Some(field.text().await.map_err(mp_err)?),
            "file_exe" => {
                let fname = field.file_name().unwrap_or("").to_string();
                let bytes = field.bytes().await.map_err(mp_err)?.to_vec();
                file_exe = Some((fname, bytes));
            }
            "file_pdb" => {
                let fname = field.file_name().unwrap_or("").to_string();
                let bytes = field.bytes().await.map_err(mp_err)?.to_vec();
                file_pdb = Some((fname, bytes));
            }
            _ => {}
        }
    }

    let name = match name {
        Some(n) => n,
        None => return Ok(upd_err("参数不完整（需要 name, type, exe）")),
    };
    let svc_type = match svc_type {
        Some(t) => t,
        None => return Ok(upd_err("参数不完整（需要 name, type, exe）")),
    };
    let exe = match exe {
        Some(e) => e,
        None => return Ok(upd_err("参数不完整（需要 name, type, exe）")),
    };

    // 上传文件校验 (对齐 legacy ServiceRoute.api_update_service)。
    let (exe_fname, exe_bytes) = match file_exe {
        Some(v) => v,
        None => return Ok(upd_err("未找到上传的 .exe 文件")),
    };
    let (pdb_fname, pdb_bytes) = match file_pdb {
        Some(v) => v,
        None => return Ok(upd_err("未找到上传的 .pdb 文件")),
    };
    if exe_fname.is_empty() {
        return Ok(upd_err("未选择 .exe 文件"));
    }
    if pdb_fname.is_empty() {
        return Ok(upd_err("未选择 .pdb 文件"));
    }
    if exe_fname.to_lowercase() != exe.to_lowercase() {
        return Ok(upd_err(&format!(
            "上传的 .exe 文件名 {} 与配置的 {} 不匹配",
            exe_fname, exe
        )));
    }
    if stem_lower(&exe_fname) != stem_lower(&pdb_fname) {
        return Ok(upd_err(&format!(
            "上传的 .exe 文件 ({exe_fname}) 和 .pdb 文件 ({pdb_fname}) 的基本文件名不匹配"
        )));
    }

    let res = tokio::task::spawn_blocking(move || {
        do_update(&state, &name, &svc_type, &exe, &exe_bytes, &pdb_bytes)
    })
    .await
    .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
    let (success, message) = res;
    Ok((StatusCode::OK, Json(json!({ "success": success, "message": message }))))
}

// ---- 内部实现 ----

/// abspath/name/type/exe 完整路径 (对齐 legacy os.path.join + normpath)。
fn exe_path(abspath: &str, name: &str, svc_type: &str, exe: &str) -> PathBuf {
    PathBuf::from(abspath).join(name).join(svc_type).join(exe)
}

/// 文件名去扩展名 (对齐 legacy os.path.splitext()[0].lower())。
fn stem_lower(fname: &str) -> String {
    PathBuf::from(fname)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(fname)
        .to_lowercase()
}

/// config 中确保 name 组与 {type,exe} 条目存在; 返回是否发生了变更。
/// 对齐 legacy deploy_service: name 不存在则建空组; type 已存在则不动。
fn ensure_service_entry(config: &mut Value, name: &str, svc_type: &str, exe: &str) -> bool {
    if config.get("service").and_then(|s| s.as_object()).is_none() {
        config["service"] = Value::Object(Default::default());
    }
    let services = config["service"].as_object_mut().unwrap();
    let list = services.entry(name.to_string()).or_insert_with(|| Value::Array(vec![]));
    let arr = match list.as_array_mut() {
        Some(a) => a,
        None => {
            *list = Value::Array(vec![]);
            list.as_array_mut().unwrap()
        }
    };
    let exists = arr
        .iter()
        .any(|e| e.get("type").and_then(|t| t.as_str()) == Some(svc_type));
    if exists {
        return false;
    }
    arr.push(json!({ "type": svc_type, "exe": exe }));
    true
}

/// sc create 注册 Windows 服务。主判据 exit code 0 (sc 输出是控制台 OEM 编码,
/// 中文 "成功" 检测不可靠), 辅判据 stdout 含 "SUCCESS"。
fn sc_create(service_name: &str, bin_path: &str, display_name: &str) -> bool {
    let out = std::process::Command::new("sc")
        .args([
            "create",
            service_name,
            &format!("binPath={bin_path}"),
            &format!("DisplayName={display_name}"),
            "start=",
            "demand",
        ])
        .output();
    match out {
        Ok(o) => {
            o.status.success()
                || String::from_utf8_lossy(&o.stdout).to_uppercase().contains("SUCCESS")
        }
        Err(_) => false,
    }
}

/// start-all 后台主体。读取 script.json 决定顺序 (对齐 legacy start_all_services):
/// - script.json 缺失/空对象 -> 按 config.json service 顺序全启
/// - 否则按 start_order 数组 (当前 script.json 只有 scripts[], 无 start_order -> 启动 0 个, 与 legacy 现状一致)
fn run_start_all(
    config_path: &std::path::Path,
    path_map: &crate::path_map::PathMap,
) -> Result<()> {
    path_map.refresh(config_path)?;
    let config = crate::routes::read_config_value(config_path)?;
    match read_script_order(config_path) {
        None => {
            for (name, svc_type, exe) in collect_config_order(&config) {
                start_one(&name, &svc_type, &exe);
            }
        }
        Some(names) => {
            let service = config.get("service").and_then(|s| s.as_object());
            for name in names {
                match service.and_then(|s| s.get(&name)).and_then(|l| l.as_array()) {
                    Some(list) => {
                        for entry in list {
                            if let (Some(t), Some(e)) = (
                                entry.get("type").and_then(|v| v.as_str()),
                                entry.get("exe").and_then(|v| v.as_str()),
                            ) {
                                start_one(&name, t, e);
                            }
                        }
                    }
                    None => tracing::warn!("start-all: 服务组 {name} 不存在"),
                }
            }
        }
    }
    Ok(())
}

/// 读 script.json 启动顺序: None=走 config 默认顺序, Some=start_order 数组。
/// 缺省文件/空对象 -> None (对齐 legacy `if not script`); 有键但无 start_order -> Some(空)。
fn read_script_order(config_path: &std::path::Path) -> Option<Vec<String>> {
    let script_path = config_path.parent().map(|p| p.join("script.json"))?;
    let raw = match std::fs::read_to_string(&script_path) {
        Ok(r) => r,
        Err(_) => return None,
    };
    let script: Value = serde_json::from_str(&raw).ok()?;
    if script.is_null() || script.as_object().map(|o| o.is_empty()).unwrap_or(false) {
        return None;
    }
    Some(
        script
            .get("start_order")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default(),
    )
}

/// config.json service 段按 JSON 键序收集 (name,type,exe)。
fn collect_config_order(config: &Value) -> Vec<(String, String, String)> {
    let mut out = Vec::new();
    if let Some(obj) = config.get("service").and_then(|s| s.as_object()) {
        for (name, list) in obj {
            if let Some(arr) = list.as_array() {
                for entry in arr {
                    if let (Some(t), Some(e)) = (
                        entry.get("type").and_then(|v| v.as_str()),
                        entry.get("exe").and_then(|v| v.as_str()),
                    ) {
                        out.push((name.clone(), t.to_string(), e.to_string()));
                    }
                }
            }
        }
    }
    out
}

fn start_one(name: &str, svc_type: &str, exe: &str) {
    let id = format!("{name}_{svc_type}");
    match crate::svc_control::imp::start(&id) {
        Ok(m) => tracing::info!("start-all {id} (exe={exe}): {m}"),
        Err(m) => tracing::warn!("start-all {id} (exe={exe}): {m}"),
    }
}

/// 热更新主体 (阻塞): 停 -> sleep 2s -> 替换 exe/pdb -> 启。
fn do_update(
    state: &AppState,
    name: &str,
    svc_type: &str,
    exe: &str,
    exe_bytes: &[u8],
    pdb_bytes: &[u8],
) -> (bool, String) {
    let _ = state.path_map.refresh(&state.config_path);
    let abspath = state.path_map.abspath();
    let exe_path = exe_path(&abspath, name, svc_type, exe);
    if !exe_path.exists() {
        return (false, format!("服务文件不存在，无法更新: {}", exe_path.display()));
    }
    let pdb_path = exe_path.with_extension("pdb");
    let id = format!("{name}_{svc_type}");
    let display = display(&id);
    // 1. 停服务 (已停止/不存在视为成功, 对齐 legacy 文案白名单)。
    if let Err(m) = crate::svc_control::imp::stop(&id) {
        if !["不存在", "已经停止", "未找到"].iter().any(|k| m.contains(k)) {
            return (false, format!("停止服务失败，无法更新: {m}"));
        }
    }
    // 2. 等进程退出。
    std::thread::sleep(std::time::Duration::from_secs(2));
    // 3. 替换文件 (legacy 用 open 'wb' 直接覆盖, 停服后无 busy 冲突)。
    if let Err(e) = std::fs::write(&exe_path, exe_bytes) {
        return (false, format!("替换文件时发生错误: {e}"));
    }
    if let Err(e) = std::fs::write(&pdb_path, pdb_bytes) {
        return (false, format!("替换文件时发生错误: {e}"));
    }
    // 4. 重启。
    match crate::svc_control::imp::start(&id) {
        Ok(_) => (true, format!("服务 {display} 更新并启动成功")),
        Err(m) => (true, format!("服务 {display} 文件已更新，但启动失败: {m}")),
    }
}

fn upd_err(msg: &str) -> (StatusCode, Json<Value>) {
    (StatusCode::BAD_REQUEST, Json(json!({ "success": false, "message": msg })))
}

fn mp_err(e: axum::extract::multipart::MultipartError) -> AppError {
    AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::json;
    use tempfile::tempdir;

    #[rstest]
    #[case("Game.exe", "game")]
    #[case("Game.EXE", "game")]
    #[case("roomsvr", "roomsvr")]
    #[case("", "")]
    fn test_stem_lower(#[case] input: &str, #[case] expected: &str) {
        assert_eq!(stem_lower(input), expected);
    }

    /// ensure_service_entry: 新组建组 + 加条目; 已有 type 不动; 返回变更标志。
    #[test]
    fn test_ensure_service_entry() {
        let mut config = json!({ "service": { "xzmo": [{ "type": "server_game", "exe": "A.exe" }] } });
        // 新组
        assert!(ensure_service_entry(&mut config, "zgda", "server_room", "R.exe"));
        assert_eq!(
            config["service"]["zgda"][0],
            json!({ "type": "server_room", "exe": "R.exe" })
        );
        // 已有 type -> 不变更
        assert!(!ensure_service_entry(&mut config, "xzmo", "server_game", "B.exe"));
        assert_eq!(config["service"]["xzmo"].as_array().unwrap().len(), 1);
        // 新 type 追加
        assert!(ensure_service_entry(&mut config, "xzmo", "server_chunk", "C.exe"));
        assert_eq!(config["service"]["xzmo"].as_array().unwrap().len(), 2);
    }

    /// collect_config_order: 按 JSON 键序展开 service 段。
    #[test]
    fn test_collect_config_order() {
        let config = json!({
            "service": {
                "zgda": [{ "type": "server_room", "exe": "R.exe" }],
                "xzmo": [
                    { "type": "server_game", "exe": "G.exe" },
                    { "type": "server_chunk", "exe": "C.exe" }
                ]
            }
        });
        assert_eq!(
            collect_config_order(&config),
            vec![
                ("zgda".into(), "server_room".into(), "R.exe".into()),
                ("xzmo".into(), "server_game".into(), "G.exe".into()),
                ("xzmo".into(), "server_chunk".into(), "C.exe".into()),
            ]
        );
    }

    /// read_script_order: 缺文件/空对象 -> None (config 默认序); 有键无 start_order -> Some(空);
    /// 有 start_order -> Some(名称列表)。
    #[test]
    fn test_read_script_order() {
        let dir = tempdir().unwrap();
        let config = dir.path().join("config.json");
        std::fs::write(&config, "{}").unwrap();
        // 无 script.json
        assert!(read_script_order(&config).is_none());
        // 空对象
        std::fs::write(dir.path().join("script.json"), "{}").unwrap();
        assert!(read_script_order(&config).is_none());
        // 有键无 start_order (当前生产 script.json 形态: 只有 scripts[])
        std::fs::write(
            dir.path().join("script.json"),
            json!({ "scripts": [{ "name": "x", "sequence": [] }] }).to_string(),
        )
        .unwrap();
        assert_eq!(read_script_order(&config), Some(vec![]));
        // 有 start_order
        std::fs::write(
            dir.path().join("script.json"),
            json!({ "start_order": ["zgda", "xzmo"] }).to_string(),
        )
        .unwrap();
        assert_eq!(read_script_order(&config), Some(vec!["zgda".into(), "xzmo".into()]));
    }

    /// sc_create 外部副作用不测; 这里仅锁死 deploy 的路径拼装。
    #[test]
    fn test_exe_path_join() {
        assert_eq!(
            exe_path("D:/game/", "xzmo", "server_game", "xzmoSvr.exe"),
            PathBuf::from("D:/game/xzmo/server_game/xzmoSvr.exe")
        );
    }
}

fn display(service_id: &str) -> String {
    if let Some(idx) = service_id.find('_') {
        let (name, t) = service_id.split_at(idx);
        format!("同城游_{}{}", name, t)
    } else {
        service_id.to_string()
    }
}

// 静默 StatusCode 占位 (json_err 返 _status 字段供 caller 选用, handler 当前都用 200
// 对齐 legacy 默认 200 文案模式; 此处保 StatusCode import 不被裁)
#[allow(dead_code)]
fn _silence_statuscode() -> StatusCode {
    StatusCode::OK
}
