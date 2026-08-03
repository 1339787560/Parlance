//! GET /api/fetch-title?url=X — 抓页面标题 (reqwest + 字符串提取 <title>)。
//!
//! 自包含 (无 legacy 数据/缓存耦合), 从简到难迁移的起点。

use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::extract::{Query, State};
use axum::Json;
use serde::{Deserialize, Serialize};

const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3";

#[derive(Deserialize)]
pub struct UrlParam {
    pub url: String,
}

#[derive(Serialize)]
pub struct TitleResp {
    pub success: bool,
    pub title: String,
}

pub async fn fetch_title(
    State(state): State<AppState>,
    Query(p): Query<UrlParam>,
) -> Result<Json<TitleResp>> {
    if p.url.is_empty() {
        return Err(AppError::MissingParam("url"));
    }
    let url = normalize_url(&p.url);

    let resp = state
        .http_client
        .get(&url)
        .header("User-Agent", UA)
        .send()
        .await
        .map_err(reqwest_err)?;
    let text = resp
        .text()
        .await
        .map_err(reqwest_err)?;

    // 提取失败兜底用 url (与旧 Flask soup.title 缺省返 url 一致)。
    let title = extract_title(&text).unwrap_or_else(|| url.clone());
    Ok(Json(TitleResp { success: true, title }))
}

fn normalize_url(url: &str) -> String {
    if url.starts_with("http://") || url.starts_with("https://") {
        url.to_string()
    } else {
        format!("http://{url}")
    }
}

fn reqwest_err(e: reqwest::Error) -> AppError {
    AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))
}

/// 从 HTML 提取 <title> 内容 (大小写不敏感定位标签, 去 trim)。
pub fn extract_title(html: &str) -> Option<String> {
    let lower = html.to_lowercase();
    let tag_start = lower.find("<title")?;
    let after_tag_open = &html[tag_start..];
    let gt = after_tag_open.find('>')?;
    let body_start = tag_start + gt + 1;
    let rest = &html[body_start..];
    let close = rest.to_lowercase().find("</title>")?;
    Some(rest[..close].trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    /// <title> 提取矩阵 (大小写/属性/空格/嵌套标签)。
    #[rstest]
    #[case("<html><head><title>你好世界</title></head>", "你好世界")]
    #[case("<TITLE>Big</TITLE>", "Big")]
    #[case("<title>  spaced  </title>", "spaced")]
    #[case("<title attr='x'>Attr</title>", "Attr")]
    #[case("<title>nested <b>bold</b> title</title>", "nested <b>bold</b> title")]
    fn test_extract_title_present(#[case] html: &str, #[case] expected: &str) {
        assert_eq!(extract_title(html).as_deref(), Some(expected));
    }

    #[rstest]
    fn test_extract_title_absent_returns_none() {
        assert_eq!(extract_title("<html>no title here</html>"), None);
    }

    #[rstest]
    #[case("example.com", "http://example.com")]
    #[case("http://x.com", "http://x.com")]
    #[case("https://y.com", "https://y.com")]
    fn test_normalize_url(#[case] input: &str, #[case] expected: &str) {
        assert_eq!(normalize_url(input), expected);
    }
}
