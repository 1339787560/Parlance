//! 数据迁移测试端点 —— U6 迁移 (2026-09-22)。
//!
//! 迁移自 legacy `CustomRoute/MigrationRoute.py` 一条：`POST /api/migration/dryrun`
//! （deposit 页 Creator 组「获取装载迁移数据」tab 的后端）。
//!
//! 数据源 = **本机 chunkSvr 的调试 HTTP 口**（缺省 `127.0.0.1:60463/v1.0/chunkluareq`），
//! 打 Lua 侧 `migrationdryrun`：对指定 uid 跑「三档判定 + 采集 Lua 侧 5 项 + 组装推送
//! 载荷」，把**会推给 CP 的那份载荷原文**返回页面。**全程只读干跑**：不推送、不写去重
//! 缓存、不落任何状态。
//!
//! **为什么 Rust 原生（不引助手）**：本条是**纯 HTTP + JSON 整形** —— 无凭据解密、无
//! 数据库、无 Python 专有语义，Rust 侧 `reqwest` + `serde_json` 已足够（沿用
//! `routes/money.rs` 的出站调用范式）。故不像 U3/U4/U6-CP 那样挂 Python 助手。
//!
//! 安全边界（与 legacy 同）：
//!   - 全程只读；不触碰 CP / 125 / 任何数据库。
//!   - 依赖本机 chunkSvr 正在运行且调试口开启（ini `[HttpServerModule] port=60463`）；
//!     不可达时返回明确错误，**不重试、不降级**。
//!   - ⚠ chunkSvr 生产侧「不得以任何形式暴露 HTTP」是运营约束；本通路口只面向**本机
//!     调试口**，不构成生产暴露面。本页签仅用于本地/联调，上线勿依赖。
//!
//! 与 legacy 的唯一有意差异：legacy 的 `MIGRATION_ENABLED` 是**硬编码 True**（其 503
//! 分支不可达）。这里改成 **env `SERVICESVR_MIGRATION_ENABLED`（缺省开）** —— 保留
//! 「可关」的能力且无需改代码重编译；不设该环境变量时行为与 legacy 完全一致。

use crate::error::Result;
use crate::state::AppState;
use axum::extract::State;
use axum::http::{header, StatusCode};
use axum::Json;
use serde_json::{json, Value};
use std::time::Duration;

/// 本机 chunkSvr 调试口；可用环境变量覆盖以指向别的机器做联调（同 legacy 的 env 名）。
const DEFAULT_CHUNKSVR_DEBUG_URL: &str = "http://127.0.0.1:60463/v1.0/chunkluareq";
/// 对齐 legacy `DRYRUN_TIMEOUT = 25`。
const DRYRUN_TIMEOUT: Duration = Duration::from_secs(25);
/// 对齐 legacy `MAX_USERID`。
const MAX_USERID: i64 = 2_i64.pow(31) - 1;

fn err(status: u16, msg: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_REQUEST),
        Json(json!({ "success": false, "message": msg })),
    )
}

fn chunksvr_url() -> String {
    std::env::var("CHUNKSVR_DEBUG_URL").unwrap_or_else(|_| DEFAULT_CHUNKSVR_DEBUG_URL.to_string())
}

/// 迁移测试面开关（缺省开；`0` / `false` / `off` 视为关 —— 见模块头注的差异说明）。
/// 返回 `Some(503 响应)` = 已关闭。
pub fn disabled_response() -> Option<(StatusCode, Json<Value>)> {
    let raw = std::env::var("SERVICESVR_MIGRATION_ENABLED").ok()?;
    let v = raw.trim().to_ascii_lowercase();
    if v == "0" || v == "false" || v == "off" || v == "no" {
        Some(err(503, "迁移测试面已关闭"))
    } else {
        None
    }
}

/// 解析玩家ID（对齐 legacy `int(body.get('userid'))` 的现实语义：JSON 数字、
/// 数字字符串；越界 → 超出范围）。
///
/// 说明：Python `int()` 还接受全角数字 / 下划线分隔等边角写法，本实现只支持
/// ASCII 十进制（trim + 可选下划线）。本端点是**页面驱动**（前端发 JSON 数字），
/// 这类边角输入不存在于真实调用；真遇到时本实现更严格（400 而非静默接受）。
pub fn parse_userid(v: Option<&Value>) -> std::result::Result<i64, (u16, &'static str)> {
    let uid = match v {
        Some(Value::Number(n)) => match n.as_i64() {
            Some(i) => i,
            None => match n.as_f64() {
                // 对齐 Python `int(float)` 向零截断
                Some(f) => f.trunc() as i64,
                None => return Err((400, "玩家ID格式错误")),
            },
        },
        Some(Value::String(s)) => {
            let t = s.trim().replace('_', "");
            match t.parse::<i64>() {
                Ok(i) => i,
                Err(_) => return Err((400, "玩家ID格式错误")),
            }
        }
        _ => return Err((400, "玩家ID格式错误")),
    };
    if uid <= 0 || uid > MAX_USERID {
        return Err((400, "玩家ID超出范围"));
    }
    Ok(uid)
}

/// `POST /api/migration/dryrun` —— `{userid}` → chunkSvr 干跑出的迁移推送载荷（只读）。
pub async fn dryrun(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    if let Some(resp) = disabled_response() {
        return Ok(resp);
    }
    let userid = match parse_userid(body.get("userid")) {
        Ok(u) => u,
        Err((st, msg)) => return Ok(err(st, msg)),
    };

    let url = chunksvr_url();
    // 只传 userid：缩写/版本由 C++ 在真实推送时从客户端登录尾载荷填入，
    // 本页不提供也不伪造（见模块头注释与页签说明）。
    let req_body = json!({ "req": "migrationdryrun", "nUserID": userid }).to_string();

    let resp = match state
        .http_client
        .post(&url)
        .header(header::CONTENT_TYPE, "application/json")
        .body(req_body)
        .timeout(DRYRUN_TIMEOUT)
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            return Ok(err(502, &format!("连不上本机 chunkSvr 调试口（{url}）：{e}")));
        }
    };

    // legacy 用 urllib（非 2xx 抛 HTTPError）→ 同义：非 2xx 一律报 code，不解析 body
    let status = resp.status();
    if !status.is_success() {
        return Ok(err(502, &format!("chunkSvr 调试口返回 HTTP {}", status.as_u16())));
    }

    let text = resp.text().await.unwrap_or_default();
    let outer: Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(_) => return Ok(err(502, "chunkSvr 返回结构异常")),
    };
    if !outer.is_object() {
        return Ok(err(502, "chunkSvr 返回结构异常"));
    }
    if let Some(e) = outer.get("err").and_then(|v| v.as_str()) {
        if !e.is_empty() {
            return Ok(err(502, &format!("chunkSvr: {e}")));
        }
    }

    // ret 可能是 JSON 对象，也可能是「对象的 JSON 字符串」（双层编码）
    let mut ret = outer.get("ret").cloned().unwrap_or(Value::Null);
    if let Value::String(s) = ret.clone() {
        match serde_json::from_str::<Value>(&s) {
            Ok(v) => ret = v,
            Err(_) => {
                let head: String = s.chars().take(200).collect();
                return Ok(err(502, &format!("chunkSvr 返回非 JSON: {head}")));
            }
        }
    }
    let success = ret.get("success").and_then(Value::as_bool).unwrap_or(false);
    if !ret.is_object() || !success {
        let e = ret.get("err").cloned().unwrap_or(ret.clone());
        return Ok(err(502, &format!("chunkSvr 干跑失败: {e}")));
    }

    let payload_str = ret
        .get("payload")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let payload_obj = if payload_str.is_empty() {
        Value::Null
    } else {
        serde_json::from_str::<Value>(&payload_str).unwrap_or(Value::Null)
    };

    Ok((
        StatusCode::OK,
        Json(json!({ "success": true, "data": {
            "userid": userid,
            "len": ret.get("len").cloned().unwrap_or(Value::Null),
            "payload": payload_str,
            "payload_obj": payload_obj,
            "source": url,
        }})),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    /// userid 解析矩阵（对齐 legacy `int()` 的现实语义 + 越界文案）。
    #[rstest]
    #[case::ok_int(Some(json!(1040720)), Ok(1040720))]
    #[case::ok_str(Some(json!("1040720")), Ok(1040720))]
    #[case::ok_str_spaces(Some(json!(" 1040720 ")), Ok(1040720))]
    #[case::ok_str_underscore(Some(json!("1_040_720")), Ok(1040720))]
    #[case::ok_float_trunc(Some(json!(1040720.9)), Ok(1040720))]
    #[case::ok_max(Some(json!(2147483647i64)), Ok(2147483647))]
    #[case::absent(None, Err((400, "玩家ID格式错误")))]
    #[case::null(Some(json!(null)), Err((400, "玩家ID格式错误")))]
    #[case::bad_str(Some(json!("abc")), Err((400, "玩家ID格式错误")))]
    #[case::float_str(Some(json!("1.5")), Err((400, "玩家ID格式错误")))]
    #[case::zero(Some(json!(0)), Err((400, "玩家ID超出范围")))]
    #[case::negative(Some(json!(-1)), Err((400, "玩家ID超出范围")))]
    #[case::too_big(Some(json!(2147483648i64)), Err((400, "玩家ID超出范围")))]
    fn test_parse_userid_matrix(
        #[case] v: Option<Value>,
        #[case] expect: std::result::Result<i64, (u16, &'static str)>,
    ) {
        assert_eq!(parse_userid(v.as_ref()), expect);
    }

    /// 关闭开关的取值集合（缺省 = 开）。
    #[test]
    fn test_migration_switch_semantics() {
        // 不设环境变量 -> None（不拦截）。注意：测试进程可能被外部污染，故只断言
        // 「显式关」的取值能触发，且不影响其它取值。
        for off in ["0", "false", "FALSE", " off ", "no"] {
            std::env::set_var("SERVICESVR_MIGRATION_ENABLED", off);
            let r = disabled_response();
            assert!(r.is_some(), "value={off:?} 应视为关闭");
            let (st, _) = r.unwrap();
            assert_eq!(st.as_u16(), 503);
        }
        for on in ["1", "true", "on", "yes", ""] {
            std::env::set_var("SERVICESVR_MIGRATION_ENABLED", on);
            assert!(disabled_response().is_none(), "value={on:?} 应视为开启");
        }
        std::env::remove_var("SERVICESVR_MIGRATION_ENABLED");
        assert!(disabled_response().is_none());
    }
}
