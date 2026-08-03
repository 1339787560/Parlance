//! GET /api/templates/get + POST /api/templates/save + POST /api/templates/delete
//!
//! shape 对齐 legacy CustomRoute/ServiceRoute.py templates 三路由:
//!   save {name,type,data} -> {success,message,id}
//!   get -> {success,templates:[{id,name,type,data}]}
//!   delete {id} -> {success,message}
//! 模板存储走 AppState.templates; 未启用 (None) -> 500 错误。

use crate::error::Result;
use crate::state::AppState;
use axum::extract::State;
use axum::Json;
use serde::Deserialize;

#[derive(Deserialize)]
pub struct SaveReq {
    pub name: String,
    #[serde(rename = "type")]
    pub svc_type: String,
    pub data: serde_json::Value,
}

#[derive(Deserialize)]
pub struct DeleteReq {
    pub id: i64,
}

/// POST /api/templates/save — 写入模板, 返新 id。
pub async fn save(
    State(state): State<AppState>,
    Json(req): Json<SaveReq>,
) -> Result<Json<serde_json::Value>> {
    let store = state.templates.as_ref().ok_or_else(|| {
        crate::error::AppError::Io(std::io::Error::new(
            std::io::ErrorKind::Other,
            "templates store not configured",
        ))
    })?;
    if req.name.is_empty() || req.data.is_null() {
        return Ok(Json(serde_json::json!({
            "success": false,
            "message": "参数不完整"
        })));
    }
    let id = store.add(&req.name, &req.svc_type, &req.data)?;
    Ok(Json(serde_json::json!({
        "success": true,
        "message": "模板保存成功",
        "id": id,
    })))
}

/// GET /api/templates/get — 全量拉取模板。
pub async fn get(State(state): State<AppState>) -> Result<Json<serde_json::Value>> {
    let store = state.templates.as_ref().ok_or_else(|| {
        crate::error::AppError::Io(std::io::Error::new(
            std::io::ErrorKind::Other,
            "templates store not configured",
        ))
    })?;
    let templates = store.all()?;
    Ok(Json(serde_json::json!({
        "success": true,
        "templates": templates,
    })))
}

/// POST /api/templates/delete — 按 id 删。
pub async fn delete(
    State(state): State<AppState>,
    Json(req): Json<DeleteReq>,
) -> Result<Json<serde_json::Value>> {
    let store = state.templates.as_ref().ok_or_else(|| {
        crate::error::AppError::Io(std::io::Error::new(
            std::io::ErrorKind::Other,
            "templates store not configured",
        ))
    })?;
    if req.id == 0 {
        return Ok(Json(serde_json::json!({
            "success": false,
            "message": "模板ID不能为空"
        })));
    }
    let hit = store.delete(req.id)?;
    Ok(if hit {
        Json(serde_json::json!({ "success": true, "message": "模板删除成功" }))
    } else {
        Json(serde_json::json!({ "success": false, "message": "模板不存在或删除失败" }))
    })
}
