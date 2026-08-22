//! SSE 实时广播：请求落库后向订阅看板推送 `new_data` 事件。

use axum::response::sse::{Event, KeepAlive, Sse};
use futures_util::stream::Stream;
use std::convert::Infallible;
use tokio::sync::broadcast;

/// SSE 事件载荷（与旧 `broadcast(event, data)` 语义对齐）。
#[derive(Debug, Clone)]
pub struct SsePayload {
    pub event: &'static str,
    pub data: String,
}

/// 广播信道：新请求完成时发 `new_data`。
pub type SseSender = broadcast::Sender<SsePayload>;

/// 创建广播信道（容量 128）。
pub fn new_channel() -> (SseSender, broadcast::Receiver<SsePayload>) {
    broadcast::channel(128)
}

/// 广播一个事件到所有订阅者。
pub fn broadcast(sender: &SseSender, event: &'static str, data: serde_json::Value) {
    let payload = SsePayload {
        event,
        data: serde_json::to_string(&data).unwrap_or_else(|_| "{}".into()),
    };
    let _ = sender.send(payload);
}

/// 构造 SSE 响应流：接收广播事件，30s keepalive。
///
/// 对齐旧 `api/events`：`event: <evt>\ndata: <json>\n\n`，超时发 keepalive 注释行。
pub fn sse_stream(
    mut rx: broadcast::Receiver<SsePayload>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let stream = async_stream::stream! {
        loop {
            match rx.recv().await {
                Ok(payload) => {
                    let evt = Event::default()
                        .event(payload.event)
                        .data(payload.data);
                    yield Ok(evt);
                }
                Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {
                    // 订阅者落后，跳过
                    continue;
                }
                Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                    break;
                }
            }
        }
    };
    Sse::new(stream).keep_alive(KeepAlive::new().interval(std::time::Duration::from_secs(30)))
}
