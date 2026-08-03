//! Strangler 反代: 未匹配请求转发到旧 Flask 后端。
//!
//! Rust 占 :5000 做前台, 已实现路由自处理, 其余 (货币调控/文件浏览/SVN 等)
//! 反代到旧 Flask (跑 :5099)。随路由迁移, Flask 渐进瘦身至退役。

use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::body::{Body, Bytes};
use axum::extract::{Request, State};
use axum::http::{Response, StatusCode};
use axum::response::IntoResponse;

/// 上限 100MB (容前端页/文件下载等大响应)。
const PROXY_BODY_CAP: usize = 100 * 1024 * 1024;

pub async fn proxy_legacy(
    State(state): State<AppState>,
    req: Request,
) -> Result<axum::response::Response> {
    let (parts, body) = req.into_parts();
    // 死功能路径 (RAG/A2A/AI 块) 不反代 legacy, 前台直接 404 强制删除。
    if is_dead_path(parts.uri.path()) {
        return Err(AppError::NotFound);
    }
    let url = compose_proxy_url(&state.legacy_backend, &parts.uri.to_string());
    let method = reqwest::Method::from_bytes(parts.method.as_str().as_bytes())
        .map_err(|_| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, "bad method")))?;

    let body_bytes = axum::body::to_bytes(body, PROXY_BODY_CAP)
        .await
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;

    let mut fwd = state.http_client.request(method, &url).body(body_bytes);
    for (k, v) in &parts.headers {
        // reqwest 自设 host 与 content-length, 跳过避免冲突。
        if k == "host" || k == "content-length" {
            continue;
        }
        if let Ok(vv) = HeaderValueCopy::try_from(v) {
            fwd = fwd.header(k, vv.0);
        }
    }

    let resp = fwd.send().await.map_err(map_reqwest_err)?;
    let status = StatusCode::from_u16(resp.status().as_u16())
        .map_err(|_| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, "bad status")))?;
    let resp_headers = resp.headers().clone();
    let resp_body: Bytes = resp
        .bytes()
        .await
        .map_err(map_reqwest_err)?;

    let mut builder = Response::builder().status(status);
    for (k, v) in &resp_headers {
        // 重新组装 body, 旧 transfer-encoding/content-length 失效, 跳过让 axum 重算。
        if k == "transfer-encoding" || k == "content-length" {
            continue;
        }
        builder = builder.header(k, v);
    }
    builder
        .body(Body::from(resp_body))
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))
        .map(|r| r.into_response())
}

fn map_reqwest_err(e: reqwest::Error) -> AppError {
    AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))
}

/// compose_proxy_url 纯函数 (可测, 避开 reqwest::HeaderValue 包装)。
pub fn compose_proxy_url(backend: &str, uri: &str) -> String {
    let backend = backend.trim_end_matches('/');
    format!("{backend}{uri}")
}

/// 死功能路径前缀 (RAG/A2A/AI 块), 命中即 404 不反代 legacy。
const DEAD_PREFIXES: &[&str] = &[
    "/ai-manager",
    "/rag-qa",
    "/api/rag",
    "/api/benchmark",
    "/api/claude",
    "/api/ai-proxy",
    "/api/makedeal",
    "/A2AManager",
    "/a2a",
];

pub fn is_dead_path(path: &str) -> bool {
    DEAD_PREFIXES.iter().any(|p| path.starts_with(p))
}

// axum HeaderValue -> reqwest HeaderValue 适配 (两边类型不同, 经 Bytes 拷贝)。
struct HeaderValueCopy(reqwest::header::HeaderValue);
impl HeaderValueCopy {
    fn try_from(v: &axum::http::HeaderValue) -> Result<Self> {
        let bytes = v.as_bytes();
        reqwest::header::HeaderValue::from_bytes(bytes)
            .map(HeaderValueCopy)
            .map_err(|_| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, "bad header")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    /// 反代 URL 拼接矩阵 (backend 尾斜杠归一 + uri 含 query 保留)。
    #[rstest]
    #[case("http://127.0.0.1:5099", "/api/x?a=1", "http://127.0.0.1:5099/api/x?a=1")]
    #[case("http://127.0.0.1:5099/", "/api/x", "http://127.0.0.1:5099/api/x")]
    #[case("http://localhost:5099", "/", "http://localhost:5099/")]
    #[case("http://127.0.0.1:5099", "/deposit#top", "http://127.0.0.1:5099/deposit#top")]
    fn test_compose_proxy_url(#[case] backend: &str, #[case] uri: &str, #[case] expected: &str) {
        assert_eq!(compose_proxy_url(backend, uri), expected);
    }

    /// 死路径前缀矩阵 (RAG/A2A/AI 块拦截)。
    #[rstest]
    #[case("/ai-manager", true)]
    #[case("/api/rag/query", true)]
    #[case("/api/benchmark/latest", true)]
    #[case("/api/claude/model", true)]
    #[case("/rag-qa", true)]
    #[case("/api/config/files", false)]
    #[case("/deposit", false)]
    #[case("/api/services/status", false)]
    fn test_is_dead_path_matrix(#[case] path: &str, #[case] dead: bool) {
        assert_eq!(is_dead_path(path), dead);
    }
}
