//! GET /recorder — 四川麻将复盘器 web 页面 + 静态资产。
//!
//! recorder.html / recorder_demo.txt / mj_color0.png 全部 include_str!/include_bytes!
//! 内嵌, 单二进制自包含 (无需外部静态目录)。
//! 后续迭代: record 解析下沉 Rust 解析器 + REST API (/api/record/list|{id})。

use axum::body::Body;
use axum::http::header::{CACHE_CONTROL, CONTENT_TYPE};
use axum::http::HeaderValue;
use axum::response::Response;

/// GET /recorder — 返复盘器页面 HTML (no-cache, 避免浏览器缓存旧版界面)。
pub async fn page() -> Response {
    let mut resp = Response::new(Body::from(include_str!("recorder.html")));
    let h = resp.headers_mut();
    h.insert(CONTENT_TYPE, HeaderValue::from_static("text/html; charset=utf-8"));
    h.insert(CACHE_CONTROL, HeaderValue::from_static("no-store"));
    resp
}

/// GET /recorder/demo — 返演示用 record 文本 (UTF-8 化的 xzms 样例)。
pub async fn demo() -> &'static str {
    include_str!("recorder_demo.txt")
}

/// GET /recorder/mj_color0.png — 川麻牌面 sprite 合图 (1024², 6×9)。
///
/// 切片规则参 memory `mj-cardface-sprite-tracker`: 万 R0 / 条 R1 / 筒 R3,
/// 9 列 x=[5,118,235,345,462,573,687,804,916], y={W:7,T:153,D:447}。
pub async fn sprite() -> Response {
    let mut resp = Response::new(Body::from(include_bytes!("mj_color0.png").as_slice()));
    let h = resp.headers_mut();
    h.insert(CONTENT_TYPE, HeaderValue::from_static("image/png"));
    h.insert(CACHE_CONTROL, HeaderValue::from_static("public, max-age=86400"));
    resp
}
