//! GET /api/services/status + GET /api/config/services/running
//!
//! status 走 TTL 缓存 (status_cache), 命中不重复 SCM syscall。running 端点
//! 额外过滤 configHide (配置编辑页不展示隐藏服务)。
//!
//! ports 字段 (Win32 only): 单次请求内一次性 snapshot 全进程 + IP Helper
//! 聚合 LISTEN 端口, 避免每服务 N 次 syscall (legacy psutil iter 慢源)。

use crate::error::Result;
use crate::ports_probe::PortsProbe;
use crate::state::AppState;
use axum::extract::State;
use axum::Json;
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
