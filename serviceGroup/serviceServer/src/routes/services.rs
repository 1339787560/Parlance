//! GET /api/services/status + GET /api/config/services/running
//!
//! status 走 TTL 缓存 (status_cache), 命中不重复 SCM syscall。running 端点
//! 额外过滤 configHide (配置编辑页不展示隐藏服务)。

use crate::error::Result;
use crate::state::AppState;
use axum::extract::State;
use axum::Json;
use std::collections::BTreeMap;

/// GET /api/services/status — 全服务状态。
pub async fn list_status(State(state): State<AppState>) -> Result<Json<serde_json::Value>> {
    state.path_map.refresh(&state.config_path)?;
    let services = state.path_map.all();
    let mut map = BTreeMap::new();
    for svc in services {
        let st = state
            .status_cache
            .get_or_query(&svc.service_id, state.status_provider.as_ref());
        map.insert(
            svc.service_id.clone(),
            serde_json::json!({
                "status": st.label(),
                "type": svc.svc_type,
                "exe": svc.exe,
                "name": svc.name,
                "path": svc.path.display().to_string(),
            }),
        );
    }
    Ok(Json(serde_json::to_value(map).unwrap()))
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
