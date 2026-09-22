//! `/static/*` 静态资源 —— 前台原生服务 (2026-09-22)。
//!
//! 迁移前: Rust 把 `/static/*` 反代给 legacy Flask (:5098), 由 Flask 的 static 目录
//! 提供 —— `CustomRoute/__init__.py` 里 `static_folder=<legacy>/src`,
//! `static_url_path=/static`。本单元把该前缀收编进前台: Rust 直读**同一份**
//! `<legacy>/src`。
//!
//! 为什么是同一个目录: `routes/assets.rs` 的抓取助手 (`assetTool.py`) 以
//! `ROOT = <legacy>` 为基准, 把抓取产物写进 `<legacy>/src/cache/...` 并返回
//! `/static/cache/...` 形式的 URL。前台改读 `<config.json 同级>/src` 即与该目录
//! 重合, fetch → 展示闭环不变 (探测/对照实测见 SDD 状态.md)。
//!
//! ## 与 legacy 的口径对齐 (2026-09-22 实测 :5098)
//!
//! | 项 | legacy | 本实现 |
//! |---|---|---|
//! | 命中 | 200 + body | 200 + body (同字节) |
//! | 缓存 | `Cache-Control: no-cache` + `ETag` + `Last-Modified` | `Cache-Control: no-cache` + `ETag` |
//! | 再验证 | `If-None-Match` 命中 → 304 | 同 |
//! | 越权 / 不存在 | 404 | 404 (不放行 legacy) |
//!
//! 两处**有意为之**的差异:
//! 1. **不发 `Last-Modified`**: 客户端再验证一律由 `ETag` 承担 (浏览器在 ETag 存在时
//!    即用它做 `If-None-Match`), 省掉手写 HTTP 日期格式化/解析这一整类边界;
//! 2. **不支持 `Range`**: 本目录只有图片/图标/JSON (无媒体), 无消费方; HTTP 允许
//!    服务端忽略 `Range` 返回 200 全量。日后若真需要, 单独加。
//!
//! Content-Type 走本模块静态表 (legacy 走 Python `mimetypes`, 表内容随机器注册表
//! 漂移 —— 例如本机 Python 未注册 `.webp` 会发 `application/octet-stream`, 本实现
//! 按标准发 `image/webp`, 浏览器按图片解码, 渲染等价)。

use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::body::Body;
use axum::extract::{Path, State};
use axum::http::{header, HeaderMap, HeaderValue, Response, StatusCode};
use std::path::{Component, Path as FsPath, PathBuf};

/// 静态根环境变量覆盖 (显式优先): 指向任意含静态产物的目录。
pub const ENV_STATIC_DIR: &str = "SERVICESVR_STATIC_DIR";

/// 静态根候选 (按优先级), 供 `resolve_static_root` 取第一个真实存在的目录:
/// 1. `SERVICESVR_STATIC_DIR` (显式覆盖)
/// 2. `<config.json 同级>/src` —— 与 `assetTool.py` 的 `ROOT/src` 同一目录 (权威锚点)
pub fn static_root_candidates(config_path: &FsPath, env_override: Option<&str>) -> Vec<PathBuf> {
    let mut out = Vec::new();
    if let Some(s) = env_override {
        if !s.trim().is_empty() {
            out.push(PathBuf::from(s.trim()));
        }
    }
    let cfg = if config_path.is_absolute() {
        config_path.to_path_buf()
    } else {
        std::env::current_dir()
            .map(|cwd| cwd.join(config_path))
            .unwrap_or_else(|_| config_path.to_path_buf())
    };
    if let Some(parent) = cfg.parent() {
        out.push(parent.join("src"));
    }
    out
}

/// 取第一个存在的静态根; 全都不可用 → None (调用方记警告, 端点一律 404)。
pub fn resolve_static_root(config_path: &FsPath, env_override: Option<&str>) -> Option<PathBuf> {
    static_root_candidates(config_path, env_override)
        .into_iter()
        .find(|p| p.is_dir())
}

/// 相对路径安全校验: 只放行"若干普通分量", 其余 (空 / 绝对 / `..` / `.` / 反斜杠 /
/// 盘符) 一律拒。axum 的 `Path` 提取器**已百分号解码**, 故 `%2e%2e%2f` 会先变成
/// `../` 再进这里被拒 —— 这是本函数同时挡住编码穿越的依据。
pub fn safe_rel_path(raw: &str) -> Option<PathBuf> {
    if raw.is_empty() || raw.starts_with('/') {
        return None;
    }
    // 反斜杠 / 冒号: Windows 上是分隔符与盘符 (Mac 上虽是普通字符, 但静态产物不会有
    // 这种命名), 统一拒绝以杜绝跨平台歧义。
    if raw.contains('\\') || raw.contains(':') {
        return None;
    }
    let mut out = PathBuf::new();
    for comp in FsPath::new(raw).components() {
        match comp {
            Component::Normal(seg) => out.push(seg),
            _ => return None, // ParentDir / RootDir / Prefix / CurDir
        }
    }
    if out.as_os_str().is_empty() {
        None
    } else {
        Some(out)
    }
}

/// 扩展名 → Content-Type (静态表, 不引 mime 依赖)。
pub fn content_type_for(path: &FsPath) -> &'static str {
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.to_ascii_lowercase())
        .unwrap_or_default();
    match ext.as_str() {
        "png" => "image/png",
        "ico" => "image/x-icon",
        "webp" => "image/webp",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "json" => "application/json",
        "html" | "htm" => "text/html; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "js" => "application/javascript; charset=utf-8",
        "txt" | "log" => "text/plain; charset=utf-8",
        "xml" => "application/xml",
        "pdf" => "application/pdf",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "ttf" => "font/ttf",
        "otf" => "font/otf",
        "mp4" => "video/mp4",
        _ => "application/octet-stream",
    }
}

/// ETag: `"<mtime秒>.<mtime纳秒>-<字节数>"`。mtime 取不到时退化为仅长度。
/// 内容不变即 ETag 稳定 —— 304 再验证的依据。
pub fn etag_for(meta: &std::fs::Metadata) -> String {
    let len = meta.len();
    let ts = meta
        .modified()
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| format!("{}.{}", d.as_secs(), d.subsec_nanos()))
        .unwrap_or_else(|| "0.0".to_string());
    format!("\"{ts}-{len}\"")
}

/// `If-None-Match` 是否命中给定 ETag。支持 `*` / 逗号列表 / 弱前缀 `W/`。
pub fn if_none_match_matches(value: Option<&HeaderValue>, etag: &str) -> bool {
    let Some(v) = value else { return false };
    let Ok(s) = v.to_str() else { return false };
    if s.trim() == "*" {
        return true;
    }
    s.split(',').any(|part| {
        let p = part.trim();
        let p = p.strip_prefix("W/").unwrap_or(p);
        p == etag
    })
}

/// ETag 串 → HeaderValue。内容仅数字/点/连字符/引号, 恒合法; 兜底不 panic。
fn etag_value(etag: &str) -> HeaderValue {
    HeaderValue::from_str(etag).unwrap_or_else(|_| HeaderValue::from_static("\"\""))
}

fn build_err(e: axum::http::Error) -> AppError {
    AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))
}

/// `GET /static/*` —— 直读静态根下的文件。
///
/// 越权 / 不存在 / 目录 → `AppError::NotFound` (404, 不放行 legacy);
/// 命中 `If-None-Match` → 304 空体 (省掉 2MB 级背景图的重复传输)。
pub async fn serve(
    State(state): State<AppState>,
    Path(raw): Path<String>,
    headers: HeaderMap,
) -> Result<Response<Body>> {
    let root = state.static_root.as_ref().ok_or(AppError::NotFound)?;
    let rel = safe_rel_path(&raw).ok_or(AppError::NotFound)?;
    let full = root.join(&rel);
    // 二次防护 (分量级): 即便 safe_rel_path 逻辑被改动绕过, 也不出静态根。
    if !crate::path_check::is_within(&full, root) {
        return Err(AppError::NotFound);
    }
    // 不存在 / 是目录 → 404 (对齐 legacy); 静态资源不把 IO 错误吐成 500。
    let meta = tokio::fs::metadata(&full)
        .await
        .ok()
        .filter(|m| m.is_file())
        .ok_or(AppError::NotFound)?;
    let etag = etag_for(&meta);

    if if_none_match_matches(headers.get(header::IF_NONE_MATCH), &etag) {
        return Response::builder()
            .status(StatusCode::NOT_MODIFIED)
            .header(header::ETAG, etag_value(&etag))
            .header(header::CACHE_CONTROL, "no-cache")
            .body(Body::empty())
            .map_err(build_err);
    }

    let bytes = tokio::fs::read(&full).await.map_err(|_| AppError::NotFound)?;
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, content_type_for(&full))
        .header(header::CONTENT_LENGTH, bytes.len().to_string())
        .header(header::ETAG, etag_value(&etag))
        .header(header::CACHE_CONTROL, "no-cache")
        .body(Body::from(bytes))
        .map_err(build_err)
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use std::sync::Arc;

    // ---- content_type_for ----

    #[rstest]
    #[case::png("a.png", "image/png")]
    #[case::png_upper("a.PNG", "image/png")]
    #[case::ico("tabIcon.ico", "image/x-icon")]
    #[case::json("friendlink.json", "application/json")]
    #[case::webp("bg_20260408.webp", "image/webp")]
    #[case::bkup("bg_20260408.webp.bkup", "application/octet-stream")]
    #[case::no_ext("noext", "application/octet-stream")]
    #[case::txt("readme.txt", "text/plain; charset=utf-8")]
    fn test_content_type_matrix(#[case] name: &str, #[case] expected: &str) {
        assert_eq!(content_type_for(FsPath::new(name)), expected);
    }

    // ---- safe_rel_path ----

    #[rstest]
    #[case::simple("tabIcon.ico", Some("tabIcon.ico"))]
    #[case::nested("cache/icons/x.png", Some("cache/icons/x.png"))]
    #[case::deep("cache/backgrounds/bg_20260408.webp.bkup", Some("cache/backgrounds/bg_20260408.webp.bkup"))]
    #[case::empty("", None)]
    #[case::parent("../config.json", None)]
    #[case::parent_nested("cache/../../config.json", None)]
    #[case::parent_tail("cache/x/..", None)]
    #[case::absolute("/etc/passwd", None)]
    #[case::dot_dir("./x", None)]
    #[case::backslash_parent("cache\\..\\config.json", None)]
    #[case::backslash_plain("cache\\x.png", None)]
    #[case::drive("C:/x.png", None)]
    #[case::colon_ads("x.png:stream", None)]
    fn test_safe_rel_path_matrix(#[case] raw: &str, #[case] expect: Option<&str>) {
        assert_eq!(safe_rel_path(raw).as_deref(), expect.map(FsPath::new));
    }

    // ---- resolve_static_root ----

    #[test]
    fn test_resolve_static_root_env_wins_over_config_sibling() {
        // Arrange: config 同级 src 与 env 目录都存在
        let cfg_dir = tempfile::tempdir().unwrap();
        let env_dir = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(cfg_dir.path().join("src")).unwrap();
        let cfg = cfg_dir.path().join("config.json");
        std::fs::write(&cfg, b"{}").unwrap();

        // Act
        let got = resolve_static_root(&cfg, Some(env_dir.path().to_str().unwrap()));

        // Assert: env 显式覆盖优先
        assert_eq!(got.as_deref(), Some(env_dir.path()));
    }

    #[test]
    fn test_resolve_static_root_falls_back_to_config_sibling() {
        let cfg_dir = tempfile::tempdir().unwrap();
        let src = cfg_dir.path().join("src");
        std::fs::create_dir_all(&src).unwrap();
        let cfg = cfg_dir.path().join("config.json");
        std::fs::write(&cfg, b"{}").unwrap();

        assert_eq!(resolve_static_root(&cfg, None).as_deref(), Some(src.as_path()));
    }

    #[test]
    fn test_resolve_static_root_none_when_no_candidate_exists() {
        let dir = tempfile::tempdir().unwrap();
        let cfg = dir.path().join("config.json"); // 无同级 src
        assert_eq!(resolve_static_root(&cfg, None), None);
    }

    // ---- etag / if_none_match ----

    #[test]
    fn test_etag_stable_for_unchanged_file_and_changes_with_content() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("a.png");
        std::fs::write(&f, b"abc").unwrap();
        let e1 = etag_for(&std::fs::metadata(&f).unwrap());
        let e2 = etag_for(&std::fs::metadata(&f).unwrap());
        assert_eq!(e1, e2, "同文件同 mtime 应稳定");
        assert!(e1.starts_with('"') && e1.ends_with('"'));
        assert!(e1.contains("-3"), "ETag 应含长度: {e1}");

        std::fs::write(&f, b"abcdef").unwrap();
        let e3 = etag_for(&std::fs::metadata(&f).unwrap());
        assert_ne!(e1, e3, "内容变化应换 ETag");
    }

    #[rstest]
    #[case::exact(Some("\"v1\""), "\"v1\"", true)]
    #[case::star(Some("*"), "\"v1\"", true)]
    #[case::weak(Some("W/\"v1\""), "\"v1\"", true)]
    #[case::list_hit(Some("\"a\", \"v1\""), "\"v1\"", true)]
    #[case::miss(Some("\"other\""), "\"v1\"", false)]
    #[case::absent(None, "\"v1\"", false)]
    fn test_if_none_match_matrix(#[case] hdr: Option<&str>, #[case] etag: &str, #[case] expected: bool) {
        let v = hdr.map(|s| HeaderValue::from_str(s).unwrap());
        assert_eq!(if_none_match_matches(v.as_ref(), etag), expected);
    }

    // ---- handler ----

    fn test_state(root: PathBuf) -> AppState {
        AppState {
            config_path: root.join("config.json"),
            path_map: Arc::new(crate::path_map::PathMap::new()),
            status_cache: Arc::new(crate::status::StatusCache::new(
                std::time::Duration::from_secs(10),
            )),
            status_provider: Arc::from(crate::status::default_provider()),
            legacy_backend: "http://127.0.0.1:5098".to_string(),
            deploy_url: "http://127.0.0.1:5099".to_string(),
            http_client: reqwest::Client::new(),
            templates: None,
            static_root: Some(root),
        }
    }

    async fn body_bytes(resp: Response<Body>) -> Vec<u8> {
        axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .unwrap()
            .to_vec()
    }

    fn tmp_static_root() -> tempfile::TempDir {
        let d = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(d.path().join("cache/icons")).unwrap();
        std::fs::write(d.path().join("cache/icons/x.png"), b"PNGDATA").unwrap();
        std::fs::write(d.path().join("extern.json"), b"{\"a\":1}").unwrap();
        d
    }

    #[tokio::test]
    async fn test_serve_returns_file_with_headers_and_conditional_304() {
        // Arrange
        let dir = tmp_static_root();
        let state = test_state(dir.path().to_path_buf());

        // Act: 首次 GET
        let resp = serve(
            State(state.clone()),
            Path("cache/icons/x.png".to_string()),
            HeaderMap::new(),
        )
        .await
        .unwrap();

        // Assert: 200 + 同字节 + 类型/缓存头
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(
            resp.headers().get(header::CONTENT_TYPE).unwrap(),
            "image/png"
        );
        assert_eq!(resp.headers().get(header::CONTENT_LENGTH).unwrap(), "7");
        assert_eq!(resp.headers().get(header::CACHE_CONTROL).unwrap(), "no-cache");
        let etag = resp
            .headers()
            .get(header::ETAG)
            .unwrap()
            .to_str()
            .unwrap()
            .to_string();
        assert_eq!(body_bytes(resp).await, b"PNGDATA");

        // Act: 带 If-None-Match 再 GET
        let mut h = HeaderMap::new();
        h.insert(
            header::IF_NONE_MATCH,
            HeaderValue::from_str(&etag).unwrap(),
        );
        let resp2 = serve(
            State(state),
            Path("cache/icons/x.png".to_string()),
            h,
        )
        .await
        .unwrap();

        // Assert: 304 空体
        assert_eq!(resp2.status(), StatusCode::NOT_MODIFIED);
        assert!(body_bytes(resp2).await.is_empty());
    }

    #[tokio::test]
    async fn test_serve_rejects_traversal_missing_and_directory() {
        // Arrange
        let dir = tmp_static_root();
        let state = test_state(dir.path().to_path_buf());

        // Act + Assert: 穿越 / 不存在 / 目录 一律 404 (不放行 legacy)
        for raw in ["../config.json", "/etc/passwd", "cache\\x.png", ""] {
            let r = serve(State(state.clone()), Path(raw.to_string()), HeaderMap::new()).await;
            assert!(matches!(r, Err(AppError::NotFound)), "raw={raw:?}");
        }
        let missing = serve(
            State(state.clone()),
            Path("nope.png".to_string()),
            HeaderMap::new(),
        )
        .await;
        assert!(matches!(missing, Err(AppError::NotFound)));
        let dir_resp = serve(
            State(state),
            Path("cache".to_string()),
            HeaderMap::new(),
        )
        .await;
        assert!(matches!(dir_resp, Err(AppError::NotFound)));
    }
}
