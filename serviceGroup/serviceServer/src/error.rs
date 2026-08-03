//! 统一错误类型, 实现 IntoResponse 直接产出与旧 Flask 兼容的 JSON 结构。

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum AppError {
    #[error("缺少参数: {0}")]
    MissingParam(&'static str),
    #[error("服务不存在: {0}")]
    ServiceNotFound(String),
    #[error("服务未运行或路径不可用")]
    ServiceUnavailable,
    #[error("路径访问被拒绝")]
    Forbidden,
    #[error("文件不存在")]
    NotFound,
    #[error("只允许访问 .ini 与 .json 与 .lua 文件")]
    InvalidExtension,
    #[error("IO 错误: {0}")]
    Io(#[from] std::io::Error),
    #[error("配置解析错误: {0}")]
    Config(#[from] serde_json::Error),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (code, msg) = match &self {
            AppError::MissingParam(_) => (StatusCode::BAD_REQUEST, self.to_string()),
            AppError::ServiceNotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            AppError::ServiceUnavailable => (StatusCode::NOT_FOUND, self.to_string()),
            AppError::Forbidden => (StatusCode::FORBIDDEN, self.to_string()),
            AppError::NotFound => (StatusCode::NOT_FOUND, self.to_string()),
            AppError::InvalidExtension => (StatusCode::BAD_REQUEST, self.to_string()),
            AppError::Io(_) => (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()),
            AppError::Config(_) => (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()),
        };
        (code, Json(json!({ "success": false, "message": msg }))).into_response()
    }
}

pub type Result<T> = std::result::Result<T, AppError>;
