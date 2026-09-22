//! 全页面面包屑注入中间件 — service-server 附属界面统一导航。
//!
//! HTML 响应（rust 内嵌页; U8 后已无反代）注入顶部条:
//!   `首页 / [当前页 ▾]`
//! 根标签"首页"可点击返回 /; 第二层为 select 下拉, 列全部页面直达切换。
//!
//! - 非 HTML 响应（JSON API/静态资源/图片）直通零开销。
//! - 注入点 `<body...>` 后; 无 body 标签 / 非 UTF-8 页面跳过（保底不破坏）。
//! - recorder 自有 fixed 顶栏 → 注入 JS 特判下移避让。

use axum::body::{to_bytes, Body};
use axum::extract::Request;
use axum::http::{header, HeaderValue};
use axum::middleware::Next;
use axum::response::Response;

/// 页面清单（path, 名称）— 面包屑第二层下拉项。
/// 首页不列（根标签"首页"本身即返回入口）; fileontimer/AIManager/A2AManager/ragQA 已退役（:5000 404），不列。
const PAGES: &[(&str, &str)] = &[
    ("/sequence", "设置启动序列"),
    ("/deposit", "设置数据"),
    ("/makecard", "做牌器"),
    ("/recorder", "复盘器"),
    ("/onlineConfigModify", "在线配置修改"),
    ("/serverstatus", "服务状态"),
];

const BAR_H: &str = "26px";

/// 首页路径判定 — "/" 与 "" 均视为首页, 不注入面包屑。
fn is_homepage(path: &str) -> bool {
    path == "/" || path.is_empty()
}

/// 注入中间件主函数。
pub async fn inject(req: Request<Body>, next: Next) -> Response {
    let path = req.uri().path().to_string();
    let resp = next.run(req).await;

    let is_html = resp
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .map(|v| v.contains("text/html"))
        .unwrap_or(false);
    if !is_html {
        return resp;
    }

    // 首页不注入面包屑（用户要求: 首页保持原样, 仅子页面带导航）
    if is_homepage(&path) {
        return resp;
    }

    let (parts, body) = resp.into_parts();
    // 16MB 上限: 页面 HTML 最大 deposit ~110KB, 富余防御
    let bytes = match to_bytes(body, 16 * 1024 * 1024).await {
        Ok(c) => c,
        Err(_) => return Response::from_parts(parts, Body::empty()),
    };
    // 非 UTF-8 HTML 不注入（legacy 模板均 UTF-8; 异常保底原样）
    let Ok(mut html) = String::from_utf8(bytes.as_ref().to_vec()) else {
        let mut parts = parts;
        parts.headers.remove(header::CONTENT_LENGTH);
        return Response::from_parts(parts, Body::from(bytes.as_ref().to_vec()));
    };

    if let Err(e) = inject_into(&mut html, &path) {
        tracing::debug!("breadcrumb 注入跳过 ({e}): {path}");
    }

    let mut parts = parts;
    parts.headers.remove(header::CONTENT_LENGTH);
    if let Ok(v) = HeaderValue::from_str(&html.len().to_string()) {
        parts.headers.insert(header::CONTENT_LENGTH, v);
    }
    Response::from_parts(parts, Body::from(html))
}

/// 在 `<body...>` 后插入面包屑条。Err = 无 body 标签（跳过注入）。
fn inject_into(html: &mut String, path: &str) -> Result<(), &'static str> {
    let body_open = html
        .find("<body")
        .and_then(|i| html[i..].find('>').map(|j| i + j + 1))
        .ok_or("no <body> tag")?;
    let snippet = build_snippet(path);
    html.insert_str(body_open, &snippet);
    Ok(())
}

/// 面包屑条 HTML+CSS+JS（自包含; Rust 端注入页面清单与当前路径）。
fn build_snippet(path: &str) -> String {
    let pages = PAGES
        .iter()
        .map(|(p, n)| format!(r#"["{p}","{n}"]"#))
        .collect::<Vec<_>>()
        .join(",");
    let is_recorder = path.starts_with("/recorder");
    // recorder 特判: 自有 fixed 顶栏 (.svc-bar top:6 / .meta top:4 / #ver-badge top:4)
    // 与 100vh 布局下移避让; 其余页面仅 html padding-top 让位。
    let recorder_css = if is_recorder {
        format!(
            ".svc-bar{{top:calc(6px + {BAR_H})!important}}\
             .meta{{top:calc(4px + {BAR_H})!important}}\
             #ver-badge{{top:calc(4px + {BAR_H})!important}}\
             .app{{height:calc(100vh - {BAR_H})!important}}"
        )
    } else {
        String::new()
    };
    format!(
        r#"<div id="svc-crumb-bar"><a class="scb-root" href="/" title="返回首页">首页</a><span class="scb-sep">/</span><select id="svc-crumb-sel" class="scb-sel" title="切换页面"></select></div>
<style>
#svc-crumb-bar{{position:fixed;top:0;left:0;right:0;height:{BAR_H};z-index:2147483000;display:flex;align-items:center;gap:6px;padding:0 10px;background:rgba(16,24,20,.95);border-bottom:1px solid rgba(255,255,255,.14);font:12px/1 "Microsoft YaHei",sans-serif;color:#cdd;backdrop-filter:blur(6px);box-sizing:border-box}}
#svc-crumb-bar .scb-root{{color:#8fd49a;font-weight:600;letter-spacing:.5px;text-decoration:none;cursor:pointer}}
#svc-crumb-bar .scb-root:hover{{color:#c9f5d1}}
#svc-crumb-bar .scb-sep{{color:#5a6a5f}}
#svc-crumb-bar .scb-sel{{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.22);border-radius:6px;color:#eef;font-size:12px;padding:1px 6px;height:20px;cursor:pointer;outline:none}}
#svc-crumb-bar .scb-sel:hover{{border-color:#8fd49a}}
#svc-crumb-bar .scb-sel option{{color:#111;background:#f5f5f5}}
html{{padding-top:{BAR_H}}}
{recorder_css}
</style>
<script>
(function(){{
  var PAGES=[{pages}];
  var sel=document.getElementById('svc-crumb-sel');
  var cur=location.pathname;
  var matched=false;
  PAGES.forEach(function(p){{
    var o=document.createElement('option');o.value=p[0];o.textContent=p[1];
    var hit=(p[0]===cur)||(p[0]==='/recorder'&&cur.indexOf('/recorder')===0);
    if(hit){{o.selected=true;matched=true}}
    sel.appendChild(o);
  }});
  if(!matched){{var o=document.createElement('option');o.textContent='(本页: '+cur+')';o.selected=true;sel.insertBefore(o,sel.firstChild)}}
  sel.onchange=function(){{if(sel.value&&sel.value!==cur)location.href=sel.value}};
}})();
</script>"#
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn injects_after_body_tag() {
        let mut html = String::from("<html><head><title>t</title></head><body class=\"x\"><p>hi</p></body></html>");
        inject_into(&mut html, "/makecard").unwrap();
        assert!(html.contains("<body class=\"x\"><div id=\"svc-crumb-bar\""));
        assert!(html.contains(r#"["/makecard","做牌器"]"#));
        // recorder 特判 CSS 仅 /recorder 注入
        let mut r = String::from("<body></body>");
        inject_into(&mut r, "/recorder").unwrap();
        assert!(r.contains(".svc-bar"));
        let mut m = String::from("<body></body>");
        inject_into(&mut m, "/makecard").unwrap();
        assert!(!m.contains(".svc-bar"));
    }

    #[test]
    fn skips_homepage() {
        // 首页路径不注入面包屑条（inject() 中间件按此纯函数短路）
        assert!(is_homepage("/"));
        assert!(is_homepage(""));
        assert!(!is_homepage("/makecard"));
        assert!(!is_homepage("/recorder"));
    }

    #[test]
    fn skips_without_body() {
        let mut html = String::from("<div>fragment</div>");
        assert!(inject_into(&mut html, "/x").is_err());
        assert_eq!(html, "<div>fragment</div>");
    }

    #[test]
    fn pages_table_sanity() {
        assert_eq!(PAGES.len(), 6);
        assert!(PAGES.iter().all(|(p, _)| p.starts_with('/')));
        let mut paths: Vec<&str> = PAGES.iter().map(|(p, _)| *p).collect();
        paths.sort();
        let n = paths.len();
        paths.dedup();
        assert_eq!(paths.len(), n, "页面路径重复");
    }
}
