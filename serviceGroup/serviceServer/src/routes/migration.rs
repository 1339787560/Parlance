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

/// Python 值语义（对齐页面对数字/字符串的宽容解析，见 `crate::pyval`）。
use crate::pyval::py_int;

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

/// 转发一条请求到 chunkSvr 调试口，返回 Lua 侧 `ret`（已解「双层编码」）。
///
/// 沿用 legacy 语义：非 2xx / 结构异常 / `err` 非空 → 一律以 (状态码, 文案) 失败，
/// 调用方直接转成 `err(...)`。**不重试、不降级**（chunkSvr 不可达是明确错误）。
pub async fn post_chunklua(
    state: &AppState,
    req: Value,
) -> std::result::Result<Value, (u16, String)> {
    let url = chunksvr_url();
    let resp = state
        .http_client
        .post(&url)
        .header(header::CONTENT_TYPE, "application/json")
        .body(req.to_string())
        .timeout(DRYRUN_TIMEOUT)
        .send()
        .await
        .map_err(|e| (502, format!("连不上本机 chunkSvr 调试口（{url}）：{e}")))?;

    // legacy 用 urllib（非 2xx 抛 HTTPError）→ 同义：非 2xx 一律报 code，不解析 body
    let status = resp.status();
    if !status.is_success() {
        return Err((502, format!("chunkSvr 调试口返回 HTTP {}", status.as_u16())));
    }

    let text = resp.text().await.unwrap_or_default();
    let outer: Value =
        serde_json::from_str(&text).map_err(|_| (502, "chunkSvr 返回结构异常".to_string()))?;
    if !outer.is_object() {
        return Err((502, "chunkSvr 返回结构异常".to_string()));
    }
    if let Some(e) = outer.get("err").and_then(|v| v.as_str()) {
        if !e.is_empty() {
            return Err((502, format!("chunkSvr: {e}")));
        }
    }

    // ret 可能是 JSON 对象，也可能是「对象的 JSON 字符串」（双层编码）
    let mut ret = outer.get("ret").cloned().unwrap_or(Value::Null);
    if let Value::String(s) = ret.clone() {
        match serde_json::from_str::<Value>(&s) {
            Ok(v) => ret = v,
            Err(_) => {
                let head: String = s.chars().take(200).collect();
                return Err((502, format!("chunkSvr 返回非 JSON: {head}")));
            }
        }
    }
    Ok(ret)
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
    let ret = match post_chunklua(&state, json!({ "req": "migrationdryrun", "nUserID": userid })).await
    {
        Ok(v) => v,
        Err((st, msg)) => return Ok(err(st, &msg)),
    };

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

// ---------- 测试面：构造测试数据（设置金币 / 设置装扮有效期 / 装扮清单） ----------
//
// 用途：验证迁移链路要构造「三类玩家」等起始态，而原测试面只能【读】：
//   ① 金币（newdeposit）  → 决定 tier1（金币 > 0）
//   ② 有时限装扮          → 决定 tier2（金币 == 0 且经验 > 0 或有时限装扮 > 0）
// 数据层全在 chunkSvr Lua（`scripts/msgcenter/Migration.lua` 的 3 个 registerhttp），
// 前台只做确定性预检 + 响应整形 —— 与 `dryrun` 同一条调试口通道，**不新增暴露面**。

/// 收集目标 uid：`userid`（单个，优先）或 `userIds`（数组）。
/// 数组内非法项静默过滤（对齐 `money.rs` 的既有口径）；全非法 / 都缺 → 400。
pub fn collect_userids(body: &Value) -> std::result::Result<Vec<i64>, (u16, &'static str)> {
    if let Some(v) = body.get("userid") {
        if !v.is_null() {
            let uid = parse_userid(Some(v)).map_err(|_| (400u16, "玩家ID格式错误"))?;
            return Ok(vec![uid]);
        }
    }
    let mut out: Vec<i64> = Vec::new();
    if let Some(arr) = body.get("userIds").and_then(Value::as_array) {
        for item in arr {
            if let Ok(uid) = parse_userid(Some(item)) {
                out.push(uid);
            }
        }
    }
    if out.is_empty() {
        return Err((400, "玩家ID格式错误"));
    }
    Ok(out)
}

/// `/api/migration/set-gold` 校验：返回 (uid 列表, 目标金币)。
pub fn validate_set_gold(body: &Value) -> std::result::Result<(Vec<i64>, i64), (u16, String)> {
    let gold = match body.get("gold") {
        None | Some(Value::Null) => return Err((400, "参数不完整（缺少 gold）".into())),
        Some(v) => match py_int(v) {
            Some(n) if n >= 0 => n,
            _ => return Err((400, "金币数量必须是非负整数".into())),
        },
    };
    let uids = collect_userids(body).map_err(|(s, m)| (s, m.to_string()))?;
    Ok((uids, gold))
}

/// `/api/migration/set-costume-expire` 校验：返回 (userid, decoration_id, expire)。
/// expire 语义：0 = 永久 / -1 = 已过期 / > 0 = N 天后过期（与 Lua 侧逐字对齐）。
pub fn validate_set_costume_expire(
    body: &Value,
) -> std::result::Result<(i64, i64, i64), (u16, String)> {
    let userid = parse_userid(body.get("userid")).map_err(|(s, m)| (s, m.to_string()))?;
    let decoration_id = match body.get("decoration_id") {
        None | Some(Value::Null) => return Err((400, "参数不完整（缺少 decoration_id）".into())),
        Some(v) => match py_int(v) {
            Some(n) if n > 0 => n,
            _ => return Err((400, "装扮ID必须是正整数".into())),
        },
    };
    let expire = match body.get("expire") {
        None | Some(Value::Null) => return Err((400, "参数不完整（缺少 expire）".into())),
        Some(v) => match py_int(v) {
            Some(n) if n >= -1 => n,
            _ => return Err((400, "有效期只支持 0(永久) / -1(过期) / 正数(有效天数)".into())),
        },
    };
    Ok((userid, decoration_id, expire))
}

/// `POST /api/migration/set-gold` —— 设置玩家金币（newdeposit）**绝对值**。
///
/// 入参 `{"userid": 123, "gold": 10000}`，或 `{"userIds": [1,2], "gold": 10000}`
/// （逐个转发并聚合，同 `money.rs` 的 deposit_proxy 范式）。金币不存在则建行。
pub async fn set_gold(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    if let Some(resp) = disabled_response() {
        return Ok(resp);
    }
    let (uids, gold) = match validate_set_gold(&body) {
        Ok(v) => v,
        Err((s, m)) => return Ok(err(s, &m)),
    };

    let mut results = Vec::new();
    let mut all_ok = true;
    for uid in &uids {
        let req = json!({ "req": "migrationsetgold", "nUserID": uid, "gold": gold });
        match post_chunklua(&state, req).await {
            Ok(ret) => {
                let ok = ret.get("success").and_then(Value::as_bool).unwrap_or(false);
                if !ok {
                    all_ok = false;
                }
                results.push(json!({ "userid": uid, "ok": ok, "result": ret }));
            }
            Err((st, msg)) => {
                all_ok = false;
                results.push(json!({ "userid": uid, "ok": false, "status": st, "error": msg }));
            }
        }
    }

    let code = if all_ok { StatusCode::OK } else { StatusCode::INTERNAL_SERVER_ERROR };
    Ok((
        code,
        Json(json!({ "success": all_ok, "gold": gold, "results": results })),
    ))
}

/// `POST /api/migration/set-costume-expire` —— 设置装扮有效期。
///
/// 入参 `{"userid": 123, "decoration_id": 3, "expire": 30}`；
/// `expire`：0 = 永久 / -1 = 已过期 / > 0 = N 天后过期（起始时间按当前时间算）。
/// **目标装扮不存在时自动新建一件有时限装扮**（便于构造 tier2 玩家）。
pub async fn set_costume_expire(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    if let Some(resp) = disabled_response() {
        return Ok(resp);
    }
    let (userid, decoration_id, expire) = match validate_set_costume_expire(&body) {
        Ok(v) => v,
        Err((s, m)) => return Ok(err(s, &m)),
    };

    let req = json!({
        "req": "migrationsetcostumeexpire",
        "nUserID": userid,
        "decoration_id": decoration_id,
        "expire": expire,
    });
    match post_chunklua(&state, req).await {
        Ok(ret) => {
            let ok = ret.get("success").and_then(Value::as_bool).unwrap_or(false);
            if !ok {
                let e = ret.get("err").cloned().unwrap_or(ret.clone());
                return Ok(err(502, &format!("chunkSvr 设置装扮有效期失败: {e}")));
            }
            Ok((StatusCode::OK, Json(json!({ "success": true, "data": ret }))))
        }
        Err((st, msg)) => Ok(err(st, &msg)),
    }
}

/// `POST /api/migration/decoration-list` —— 装扮清单（页面下拉用，只读）。
pub async fn decoration_list(State(state): State<AppState>) -> Result<(StatusCode, Json<Value>)> {
    if let Some(resp) = disabled_response() {
        return Ok(resp);
    }
    match post_chunklua(&state, json!({ "req": "migrationdecorationlist" })).await {
        Ok(ret) => {
            let ok = ret.get("success").and_then(Value::as_bool).unwrap_or(false);
            if !ok {
                let e = ret.get("err").cloned().unwrap_or(ret.clone());
                return Ok(err(502, &format!("chunkSvr 取装扮清单失败: {e}")));
            }
            Ok((StatusCode::OK, Json(json!({ "success": true, "data": ret }))))
        }
        Err((st, msg)) => Ok(err(st, &msg)),
    }
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

    // ---- 测试面：collect_userids / validate_set_gold / validate_set_costume_expire ----

    #[test]
    fn test_collect_userids_single_and_multi() {
        assert_eq!(collect_userids(&json!({"userid": 123})).unwrap(), vec![123]);
        assert_eq!(collect_userids(&json!({"userid": "123"})).unwrap(), vec![123]);
        // userIds 数组：非法项静默过滤
        assert_eq!(
            collect_userids(&json!({"userIds": [1, "2", 0, -3, "x"]})).unwrap(),
            vec![1, 2]
        );
        // userid 优先于 userIds
        assert_eq!(
            collect_userids(&json!({"userid": 9, "userIds": [1, 2]})).unwrap(),
            vec![9]
        );
    }

    #[test]
    fn test_collect_userids_errors() {
        assert_eq!(collect_userids(&json!({})).unwrap_err(), (400, "玩家ID格式错误"));
        assert_eq!(
            collect_userids(&json!({"userIds": []})).unwrap_err(),
            (400, "玩家ID格式错误")
        );
        assert_eq!(
            collect_userids(&json!({"userIds": [0, -1]})).unwrap_err(),
            (400, "玩家ID格式错误")
        );
        assert_eq!(collect_userids(&json!({"userid": 0})).unwrap_err(), (400, "玩家ID格式错误"));
        assert_eq!(
            collect_userids(&json!({"userid": 2147483648i64})).unwrap_err(),
            (400, "玩家ID格式错误")
        );
    }

    #[test]
    fn test_validate_set_gold_ok() {
        assert_eq!(
            validate_set_gold(&json!({"userid": 7, "gold": 100})).unwrap(),
            (vec![7], 100)
        );
        // 字符串数字 + 0 合法
        assert_eq!(
            validate_set_gold(&json!({"userIds": [1, 2], "gold": "0"})).unwrap(),
            (vec![1, 2], 0)
        );
    }

    #[rstest]
    #[case::no_gold(json!({"userid": 7}), "参数不完整（缺少 gold）")]
    #[case::null_gold(json!({"userid": 7, "gold": null}), "参数不完整（缺少 gold）")]
    #[case::negative(json!({"userid": 7, "gold": -1}), "金币数量必须是非负整数")]
    #[case::not_a_number(json!({"userid": 7, "gold": "abc"}), "金币数量必须是非负整数")]
    #[case::no_uid(json!({"gold": 1}), "玩家ID格式错误")]
    fn test_validate_set_gold_errors(#[case] body: Value, #[case] expected: &str) {
        assert_eq!(
            validate_set_gold(&body).unwrap_err(),
            (400, expected.to_string())
        );
    }

    #[test]
    fn test_validate_set_costume_expire_ok() {
        // 三种有效期语义：0 永久 / -1 已过期 / >0 天数
        assert_eq!(
            validate_set_costume_expire(&json!({"userid": 7, "decoration_id": 3, "expire": 0}))
                .unwrap(),
            (7, 3, 0)
        );
        assert_eq!(
            validate_set_costume_expire(&json!({"userid": 7, "decoration_id": 3, "expire": -1}))
                .unwrap(),
            (7, 3, -1)
        );
        // 字符串数字也接受
        assert_eq!(
            validate_set_costume_expire(
                &json!({"userid": "7", "decoration_id": "3", "expire": "30"})
            )
            .unwrap(),
            (7, 3, 30)
        );
    }

    #[rstest]
    #[case::no_deco(json!({"userid": 7, "expire": 1}), "参数不完整（缺少 decoration_id）")]
    #[case::bad_deco(json!({"userid": 7, "decoration_id": 0, "expire": 1}), "装扮ID必须是正整数")]
    #[case::no_expire(json!({"userid": 7, "decoration_id": 3}), "参数不完整（缺少 expire）")]
    #[case::too_negative(
        json!({"userid": 7, "decoration_id": 3, "expire": -5}),
        "有效期只支持 0(永久) / -1(过期) / 正数(有效天数)"
    )]
    #[case::no_uid(json!({"decoration_id": 3, "expire": 1}), "玩家ID格式错误")]
    fn test_validate_set_costume_expire_errors(#[case] body: Value, #[case] expected: &str) {
        assert_eq!(
            validate_set_costume_expire(&body).unwrap_err(),
            (400, expected.to_string())
        );
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
