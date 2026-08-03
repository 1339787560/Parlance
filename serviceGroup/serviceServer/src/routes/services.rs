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
use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use std::collections::BTreeMap;

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
