//! GET /recorder — 四川麻将复盘器 web 页面骨架。
//!
//! 同名 recorder.html 经 include_str! 静态内嵌, 单二进制自包含 (无需外部静态目录)。
//! 后续迭代: record 解析 + REST API 对接 + mj_color0 sprite + 4 chair + 川麻特化布局
//! (玩家区三段 meld/hand/hu + 定缺 chip + 换三张桌面正中)。

use axum::response::Html;

/// GET /recorder — 返复盘器页面 HTML。
pub async fn page() -> Html<&'static str> {
    Html(include_str!("recorder.html"))
}
