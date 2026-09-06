//! 透明代理：接收本地请求，转发到 DeepSeek API，落统计。
//!
//! 对齐旧 `proxy_server.py::proxy` 语义：
//! - 双格式检测（Anthropic / OpenAI）
//! - 模型映射 + usage 归一化
//! - 流式（SSE 逐行透传）与非流式
//! - 错误 status 语义：`http_XXX` / `upstream_XXX`

use axum::body::Body;
use axum::extract::{Path, State};
use axum::http::{header, HeaderMap, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::time::Instant;

use crate::model::{extract_usage, ApiFormat, Usage};
use crate::state::AppState;
use crate::store::{record, RequestRecord};

/// 本地端点（不进代理）：health / api/events / api/* 统计。
fn is_local(path: &str) -> bool {
    path == "health"
        || path == "api/events"
        || path.is_empty()
        || path == "/"
        || (path.starts_with("api/") && !path.starts_with("api/events"))
}

/// 通用代理入口，所有 method 都进这里。
pub async fn proxy(
    State(state): State<std::sync::Arc<AppState>>,
    method: Method,
    Path(path): Path<String>,
    headers: HeaderMap,
    body: Body,
) -> Response {
    if is_local(&path) {
        return Response::builder()
            .status(StatusCode::NOT_FOUND)
            .body(Body::from(r#"{"error":"local route handled elsewhere"}"#))
            .unwrap();
    }

    // 读激活来源的代理 key（客户端透传 Authorization/x-api-key 优先）
    let api_key = state.sources.read().await.active_api_key();
    let client_auth = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string());
    let client_api_key = headers
        .get("x-api-key")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string());
    // 无代理 key 且客户端也未提供 key → 500
    if api_key.is_empty() && client_auth.is_none() && client_api_key.is_none() {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            JsonErr(json!({"error": "no API key: set DEEPSEEK_API_KEY or provide Authorization/x-api-key header"})),
        )
            .into_response();
    }

    // 格式检测 + 目标（取激活来源的 target；同时记来源名/代理开关/映射行为）
    let (fmt, target_name) = crate::model::detect_format(&path);
    let (anthropic, openai, source_name, use_system_proxy, source_is_glm) = {
        let mgr = state.sources.read().await;
        match mgr.active_source() {
            Some(s) => (
                s.anthropic.clone(),
                s.openai.clone(),
                s.name.clone(),
                s.use_system_proxy,
                s.is_glm_provider(),
            ),
            None => (String::new(), String::new(), "unknown".to_string(), false, false),
        }
    };
    let target_base = match target_name {
        "openai" => openai,
        _ => anthropic,
    };
    let target_path = crate::model::normalize_path(&path, fmt);
    let target_url = format!("{}/{}", target_base.trim_end_matches('/'), target_path);
    tracing::debug!(target_url = %target_url, fmt = ?fmt, "proxy forwarding");

    // 读 body
    let bytes = match axum::body::to_bytes(body, 64 * 1024 * 1024).await {
        Ok(b) => b,
        Err(_) => {
            return (
                StatusCode::BAD_REQUEST,
                JsonErr(json!({"error": "read body failed"})),
            )
                .into_response();
        }
    };
    let mut body_json: Value = if bytes.is_empty() {
        json!({})
    } else {
        serde_json::from_slice(&bytes).unwrap_or(json!({}))
    };

    // 模型映射：GLM 来源透传（claude→deepseek 映射是 DS 专属，套到 GLM 会被拒）；
    // 其余来源沿用全局映射。
    let model = body_json
        .get("model")
        .and_then(Value::as_str)
        .unwrap_or("");
    let mapped_model = map_model_for_source(model, source_is_glm);
    body_json["model"] = json!(mapped_model);

    // 流式判定：OpenAI 默认非流式，Anthropic 默认流式
    let is_stream = body_json
        .get("stream")
        .and_then(Value::as_bool)
        .unwrap_or(fmt == ApiFormat::Anthropic);

    let req_id = format!("req_{}", uuid::Uuid::new_v4().simple().to_string()[..16].to_string());
    let session_id = headers
        .get("x-claude-code-session-id")
        .or_else(|| headers.get("x-session-id"))
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let start = Instant::now();

    // 构造上游请求：默认直连（no_proxy，规避智谱对代理出口 IP 的审查，F5）；
    // 来源显式 use_system_proxy=true 时走系统代理。
    let mut builder = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(300));
    if !use_system_proxy {
        builder = builder.no_proxy();
    }
    let client = builder.build().unwrap();

    let mut req = client.request(method.clone(), &target_url);
    req = req.header(header::CONTENT_TYPE, "application/json");
    // build_headers 对齐线上：auth → x-api-key → DEEPSEEK_API_KEY
    match fmt {
        ApiFormat::OpenAI => {
            if let Some(auth) = &client_auth {
                req = req.header(header::AUTHORIZATION, auth);
            } else if let Some(k) = &client_api_key {
                req = req.header(header::AUTHORIZATION, format!("Bearer {k}"));
            } else if !api_key.is_empty() {
                req = req.header(header::AUTHORIZATION, format!("Bearer {api_key}"));
            }
        }
        ApiFormat::Anthropic => {
            let version = headers
                .get("anthropic-version")
                .and_then(|v| v.to_str().ok())
                .unwrap_or("2023-06-01")
                .to_string();
            req = req.header("anthropic-version", version);
            if let Some(auth) = &client_auth {
                req = req.header(header::AUTHORIZATION, auth);
            } else if let Some(k) = &client_api_key {
                req = req.header("x-api-key", k);
            } else if !api_key.is_empty() {
                req = req.header(header::AUTHORIZATION, format!("Bearer {api_key}"));
            }
        }
    }
    req = req.json(&body_json);

    // ---- 非流式 ----
    if !is_stream {
        return handle_non_stream(state, client, req, req_id, session_id, mapped_model, fmt, start, source_name)
            .await;
    }

    // ---- 流式 ----
    handle_stream(state, client, req, req_id, session_id, mapped_model, fmt, start, source_name).await
}

/// 模型映射分派：GLM 来源透传；其余走全局 claude→deepseek 映射。
fn map_model_for_source(model: &str, source_is_glm: bool) -> String {
    if source_is_glm {
        model.to_string()
    } else {
        crate::model::map_model(model).to_string()
    }
}

/// 非流式请求处理。client 由 proxy() 按 use_system_proxy 构建后传入复用。
async fn handle_non_stream(
    state: std::sync::Arc<AppState>,
    client: reqwest::Client,
    req: reqwest::RequestBuilder,
    req_id: String,
    session_id: String,
    model: String,
    fmt: ApiFormat,
    start: Instant,
    source_name: String,
) -> Response {
    match client.execute(req.build().unwrap()).await {
        Ok(resp) => {
            let status = resp.status();
            let bytes = match resp.bytes().await {
                Ok(b) => b,
                Err(_) => {
                    return (
                        StatusCode::BAD_GATEWAY,
                        JsonErr(json!({"error": "read upstream response failed"})),
                    )
                        .into_response();
                }
            };
            if !status.is_success() {
                // 错误：透传上游错误体 + 落 http_XXX
                let body: Value = serde_json::from_slice(&bytes).unwrap_or_else(|_| {
                    json!({"error": String::from_utf8_lossy(&bytes).to_string()})
                });
                let latency = start.elapsed().as_millis() as i64;
                let _ = record(
                    &state.db.lock().unwrap(),
                    &RequestRecord {
                        id: req_id,
                        ts: crate::now_iso(),
                        session_id: session_id.clone(),
                        model: model.clone(),
                        usage: Usage::default(),
                        latency_ms: latency,
                        status: format!("http_{}", status.as_u16()),
                        format: format_name(fmt).to_string(),
                        source: source_name.clone(),
                    },
                );
                return (StatusCode::from_u16(status.as_u16()).unwrap(), JsonErr(body)).into_response();
            }
            let data: Value = serde_json::from_slice(&bytes).unwrap_or(json!({}));
            let usage = extract_usage(data.get("usage").unwrap_or(&json!({})), fmt);
            let latency = start.elapsed().as_millis() as i64;
            let _ = record(
                &state.db.lock().unwrap(),
                &RequestRecord {
                    id: req_id,
                    ts: crate::now_iso(),
                    session_id,
                    model: data
                        .get("model")
                        .and_then(Value::as_str)
                        .unwrap_or(&model)
                        .to_string(),
                    usage,
                    latency_ms: latency,
                    status: "ok".into(),
                    format: format_name(fmt).to_string(),
                    source: source_name.clone(),
                },
            );
            crate::sse::broadcast(&state.sse, "new_data", json!({}));
            (StatusCode::OK, axum::Json(data)).into_response()
        }
        Err(e) => {
            // 网络层故障
            let latency = start.elapsed().as_millis() as i64;
            let _ = record(
                &state.db.lock().unwrap(),
                &RequestRecord {
                    id: req_id,
                    ts: crate::now_iso(),
                    session_id,
                    model,
                    usage: Usage::default(),
                    latency_ms: latency,
                    status: format!("upstream_{}", err_name(&e)),
                    format: format_name(fmt).to_string(),
                    source: source_name,
                },
            );
            (
                StatusCode::BAD_GATEWAY,
                JsonErr(json!({"error": format!("upstream: {}: {}", err_name(&e), short_err(&e))})),
            )
                .into_response()
        }
    }
}

/// 流式请求处理：SSE 逐行透传，边转发边解析 usage。
/// client 由 proxy() 按 use_system_proxy 构建后传入复用。
async fn handle_stream(
    state: std::sync::Arc<AppState>,
    client: reqwest::Client,
    req: reqwest::RequestBuilder,
    req_id: String,
    session_id: String,
    model: String,
    fmt: ApiFormat,
    start: Instant,
    source_name: String,
) -> Response {
    match client.execute(req.build().unwrap()).await {
        Ok(resp) => {
            let status = resp.status();
            tracing::debug!(status = %status, "stream upstream response");
            if !status.is_success() {
                let bytes = match resp.bytes().await {
                    Ok(b) => b,
                    Err(_) => return (StatusCode::BAD_GATEWAY, JsonErr(json!({"error": "read err"}))).into_response(),
                };
                let body: Value = serde_json::from_slice(&bytes).unwrap_or_else(|_| {
                    json!({"error": String::from_utf8_lossy(&bytes).to_string()})
                });
                let latency = start.elapsed().as_millis() as i64;
                let _ = record(
                    &state.db.lock().unwrap(),
                    &RequestRecord {
                        id: req_id,
                        ts: crate::now_iso(),
                        session_id: session_id.clone(),
                        model: model.clone(),
                        usage: Usage::default(),
                        latency_ms: latency,
                        status: format!("http_{}", status.as_u16()),
                        format: format_name(fmt).to_string(),
                        source: source_name.clone(),
                    },
                );
                return (StatusCode::from_u16(status.as_u16()).unwrap(), JsonErr(body)).into_response();
            }

            // 上游返回 JSON（非 SSE）：客户端未显式带 stream 时按「Anthropic 默认流式」
            // 误入此路径（上游协议缺省非流式），或上游忽略 stream 参数——按非流式
            // 处理（整体读 body 提取 usage），否则 SSE 逐行解析提不到 usage 落 0。
            let content_type = resp
                .headers()
                .get(header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                .unwrap_or("")
                .to_ascii_lowercase();
            if !content_type.contains("text/event-stream") {
                let bytes = match resp.bytes().await {
                    Ok(b) => b,
                    Err(_) => return (StatusCode::BAD_GATEWAY, JsonErr(json!({"error": "read err"}))).into_response(),
                };
                let data: Value = serde_json::from_slice(&bytes).unwrap_or(json!({}));
                let usage = extract_usage(data.get("usage").unwrap_or(&json!({})), fmt);
                let latency = start.elapsed().as_millis() as i64;
                let resp_model = data
                    .get("model")
                    .and_then(Value::as_str)
                    .unwrap_or(&model)
                    .to_string();
                let _ = record(
                    &state.db.lock().unwrap(),
                    &RequestRecord {
                        id: req_id,
                        ts: crate::now_iso(),
                        session_id,
                        model: resp_model,
                        usage,
                        latency_ms: latency,
                        status: "ok".into(),
                        format: format_name(fmt).to_string(),
                        source: source_name,
                    },
                );
                crate::sse::broadcast(&state.sse, "new_data", json!({}));
                return (
                    StatusCode::OK,
                    [(header::CONTENT_TYPE, "application/json")],
                    bytes,
                )
                    .into_response();
            }

            // SSE 流式透传
            let db = state.db.clone();
            let sse = state.sse.clone();
            let stream = axum::body::Body::from_stream(async_stream::stream! {
                let mut usage: Value = json!({});
                let mut err = false;
                let mut byte_stream = resp.bytes_stream();
                // ponytail: 跨 chunk 缓冲不完整 SSE 行（TCP 分块会切断行首/行尾，
                // 逐行解析丢 usage → message_delta 的 usage 丢失）。行内缓冲即可，
                // 不上完整事件解析器。
                let mut pending: Vec<u8> = Vec::new();
                while let Some(chunk) = byte_stream.next().await {
                    match chunk {
                        Ok(bytes) => {
                            pending.extend_from_slice(&bytes);
                            // 按 \n 切行；末尾不完整段留在 pending 等下一 chunk
                            let mut start = 0usize;
                            while let Some(rel) = pending[start..].iter().position(|&b| b == b'\n') {
                                let end = start + rel;
                                let line = &pending[start..end];
                                let text = String::from_utf8_lossy(line);
                                parse_usage_line(&mut usage, &text, fmt);
                                start = end + 1;
                            }
                            pending.drain(..start);
                            yield Ok::<_, std::io::Error>(bytes);
                        }
                        Err(e) => {
                            err = true;
                            let msg = format!("event: error\ndata: {}\n\n", json!({"error": e.to_string()}));
                            yield Ok::<_, std::io::Error>(axum::body::Bytes::from(msg));
                            break;
                        }
                    }
                }
                // 流结束：处理残留未换行的最后一段
                if !pending.is_empty() {
                    let text = String::from_utf8_lossy(&pending);
                    parse_usage_line(&mut usage, &text, fmt);
                }
                let latency = start.elapsed().as_millis() as i64;
                if !err && !usage.is_null() && !usage.as_object().map(|o| o.is_empty()).unwrap_or(true) {
                    let u = extract_usage(&usage, fmt);
                    let _ = record(
                        &db.lock().unwrap(),
                        &RequestRecord {
                            id: req_id,
                            ts: crate::now_iso(),
                            session_id,
                            model: model.clone(),
                            usage: u,
                            latency_ms: latency,
                            status: "ok".into(),
                            format: format_name(fmt).to_string(),
                            source: source_name.clone(),
                        },
                    );
                    crate::sse::broadcast(&sse, "new_data", json!({}));
                } else if !err {
                    // 无 usage 也落一条（对齐旧逻辑）
                    let _ = record(
                        &db.lock().unwrap(),
                        &RequestRecord {
                            id: req_id,
                            ts: crate::now_iso(),
                            session_id,
                            model: model.clone(),
                            usage: Usage::default(),
                            latency_ms: latency,
                            status: "ok".into(),
                            format: format_name(fmt).to_string(),
                            source: source_name.clone(),
                        },
                    );
                }
            });

            (
                StatusCode::OK,
                [
                    (header::CONTENT_TYPE, "text/event-stream"),
                    (header::CACHE_CONTROL, "no-cache"),
                    (header::CONNECTION, "keep-alive"),
                ],
                stream,
            )
                .into_response()
        }
        Err(e) => {
            let latency = start.elapsed().as_millis() as i64;
            let _ = record(
                &state.db.lock().unwrap(),
                &RequestRecord {
                    id: req_id,
                    ts: crate::now_iso(),
                    session_id,
                    model,
                    usage: Usage::default(),
                    latency_ms: latency,
                    status: format!("upstream_{}", err_name(&e)),
                    format: format_name(fmt).to_string(),
                    source: source_name,
                },
            );
            (
                StatusCode::BAD_GATEWAY,
                JsonErr(json!({"error": format!("upstream: {}: {}", err_name(&e), short_err(&e))})),
            )
                .into_response()
        }
    }
}

/// 从一行 SSE 中提取 usage（Anthropic message_start/message_delta + OpenAI data 块）。
fn parse_usage_line(usage: &mut Value, line: &str, fmt: ApiFormat) {
    // 兼容两种 data 前缀：标准 `data: `（带空格）与紧凑 `data:`（如超算平台发送）
    let data = line
        .strip_prefix("data: ")
        .or_else(|| line.strip_prefix("data:"))
        .or_else(|| line.strip_prefix("data : "));
    if let Some(data) = data {
        if let Ok(v) = serde_json::from_str::<Value>(data) {
            match fmt {
                ApiFormat::Anthropic => {
                    if let Some(msg) = v.get("message") {
                        merge_usage(usage, msg.get("usage"));
                    } else if let Some(u) = v.get("usage") {
                        merge_usage(usage, Some(u));
                    }
                }
                ApiFormat::OpenAI => {
                    if let Some(u) = v.get("usage") {
                        merge_usage(usage, Some(u));
                    }
                }
            }
        }
    }
}

fn merge_usage(target: &mut Value, src: Option<&Value>) {
    if let Some(s) = src {
        if let Some(obj) = s.as_object() {
            let t = target.as_object_mut().unwrap();
            for (k, v) in obj {
                t.insert(k.clone(), v.clone());
            }
        }
    }
}

/// 简单的 JSON 响应包装（对齐 `{success/message}` 或错误体）。
struct JsonErr(Value);

impl IntoResponse for JsonErr {
    fn into_response(self) -> Response {
        axum::Json(self.0).into_response()
    }
}

fn format_name(fmt: ApiFormat) -> &'static str {
    match fmt {
        ApiFormat::Anthropic => "anthropic",
        ApiFormat::OpenAI => "openai",
    }
}

fn err_name(e: &reqwest::Error) -> String {
    if e.is_timeout() {
        "Timeout".into()
    } else if e.is_connect() {
        "ConnectError".into()
    } else if e.is_decode() {
        "DecodeError".into()
    } else if e.is_redirect() {
        "Redirect".into()
    } else {
        "RequestError".into()
    }
}

fn short_err(e: &reqwest::Error) -> String {
    e.to_string().chars().take(200).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_routes_excluded() {
        assert!(is_local("health"));
        assert!(is_local("api/events"));
        assert!(is_local("api/stats"));
        assert!(is_local(""));
        assert!(!is_local("v1/messages"));
        assert!(!is_local("chat/completions"));
    }

    #[test]
    fn parse_usage_anthropic() {
        let mut u = json!({});
        parse_usage_line(
            &mut u,
            r#"data: {"type":"message_start","message":{"usage":{"input_tokens":5,"output_tokens":0}}}"#,
            ApiFormat::Anthropic,
        );
        assert_eq!(u["input_tokens"], 5);
    }

    #[test]
    fn parse_usage_openai() {
        let mut u = json!({});
        parse_usage_line(
            &mut u,
            r#"data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":3}}"#,
            ApiFormat::OpenAI,
        );
        assert_eq!(u["prompt_tokens"], 7);
    }

    #[test]
    fn parse_usage_anthropic_message_delta() {
        // message_delta 顶层 usage 是真实 token 数（message_start 全 0）
        let mut u = json!({});
        parse_usage_line(
            &mut u,
            r#"data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":84,"output_tokens":33}}"#,
            ApiFormat::Anthropic,
        );
        assert_eq!(u["input_tokens"], 84);
        assert_eq!(u["output_tokens"], 33);
    }

    #[test]
    fn parse_usage_anthropic_no_space_prefix() {
        // 超算平台实际发送 `data:{...}`（冒号后无空格）——此前 strip_prefix("data: ") 全漏
        let mut u = json!({});
        parse_usage_line(
            &mut u,
            r#"data:{"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"input_tokens":84,"output_tokens":33}}"#,
            ApiFormat::Anthropic,
        );
        assert_eq!(u["input_tokens"], 84);
        assert_eq!(u["output_tokens"], 33);

        let mut u2 = json!({});
        parse_usage_line(
            &mut u2,
            r#"data:{"type":"message_start","message":{"usage":{"input_tokens":10,"output_tokens":0,"cache_read_input_tokens":5,"cache_creation_input_tokens":0}}}"#,
            ApiFormat::Anthropic,
        );
        assert_eq!(u2["input_tokens"], 10);
        assert_eq!(u2["cache_read_input_tokens"], 5);
    }

    #[test]
    fn parse_usage_line_split_across_chunks() {
        // 模拟 TCP 分块把 message_delta 行切成两半：前半（缺右括号）解析失败、
        // 后半（无 data: 前缀）跳过——单块各自解析都丢；这里验证完整行可解析
        // （跨块缓冲在流式循环内，parse_usage_line 只处理单行）。
        let mut u = json!({});
        let line = r#"data: {"type":"message_delta","usage":{"input_tokens":7}}"#;
        assert!(line.starts_with("data: "));
        parse_usage_line(&mut u, line, ApiFormat::Anthropic);
        assert_eq!(u["input_tokens"], 7);
    }
}
