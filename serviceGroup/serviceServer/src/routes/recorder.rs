//! GET /recorder — 四川麻将复盘器 web 页面 + /recorder/demo 演示 record。
//!
//! 同名 recorder.html 经 include_str! 静态内嵌, 单二进制自包含 (无需外部静态目录)。
//! recorder_demo.txt = 川麻 xzms 样例 record (UTF-8 化, GBK 原文转码) 供前端演示 fetch。
//! 后续迭代: record 解析下沉 Rust 解析器 + REST API (/api/record/list|{id})。

use axum::response::Html;

/// GET /recorder — 返复盘器页面 HTML。
pub async fn page() -> Html<&'static str> {
    Html(include_str!("recorder.html"))
}

/// GET /recorder/demo — 返演示用 record 文本 (UTF-8 化的 xzms 样例)。
///
/// 前端 fetch 后 JS 解析头部 + 事件序列渲染。后续接正式 /api/record/{id}。
pub async fn demo() -> &'static str {
    include_str!("recorder_demo.txt")
}
