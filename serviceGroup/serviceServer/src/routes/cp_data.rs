//! CP 用户数据端点 —— U6 迁移 (2026-09-22)。
//!
//! 迁移自 legacy `CustomRoute/CpDirectRoute.py` 六条（deposit 页「CP 数据」tab 的后端）：
//!
//! | 路由 | 行为 |
//! |---|---|
//! | `GET/POST /api/cp-data/direct/appcodes` | 可用缩写清单（从落盘表名派生） |
//! | `POST /api/cp-data/direct/modules` | 按 玩家ID + 缩写 列模块（redis ∪ mysql） |
//! | `POST /api/cp-data/direct/module` | 单模块明细（redis 值 + mysql 行） |
//! | `POST /api/cp-data/direct/write-prepare` | 受控写第一步：写前实时查询（只读） |
//! | `POST /api/cp-data/direct/write` | 受控写第二步：写入（存在即写；响应含 snapshot 可撤回） |
//! | `POST /api/cp-data/direct/clear` | 清空该玩家该模块（redis + mysql 两侧）⚠ 不可逆 |
//!
//! **为什么走 Python 助手**：这六条要解凭据（`db_creds.enc` 的 cp 段 + `CredsManager`）、
//! 连 CP 平台 MySQL(`modsvr283db`) 与 redis(db10)，实现全在 `CommonTools/xzmpDB/CpUserData.py`。
//! 与 U3(货币)/U4(抓取) 同法：**HTTP 面在 Rust**（参数预检 + 响应整形），
//! **数据层在 `cpDataTool.py`**（各 action 逐条搬运 legacy 路由体）。
//!
//! **参数校验分工（避免两侧规则漂移）**：Rust 只做**确定性预检** —— 仅当能确定
//! 「助手会给出完全同一文案」时才拦截（字段缺失/空串/越界/ASCII 白名单不匹配）；
//! 其余一律**原样转发**给助手，由 `cpDataTool.py`（= 原 `CpDirectRoute.py` 的校验）
//! 定夺。这样即便遇到 Python 语义的边角输入（如全角数字），行为也与 legacy 一致。

use crate::error::Result;
use crate::pybridge::{self, HelperOut};
use crate::state::AppState;
use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use serde_json::{json, Value};

/// 助手脚本名（由 `SERVICESVR_PYTHON` 解释器执行；见 `pybridge` 头注三条纪律）。
const HELPER_NAME: &str = "cpDataTool.py";

/// 玩家ID 上限（与 legacy `CpDirectRoute.MAX_USERID` 一致）。
const MAX_USERID: i64 = 2_i64.pow(31) - 1;

fn err(status: u16, msg: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_REQUEST),
        Json(json!({ "success": false, "message": msg })),
    )
}

// ---------------------------------------------------------------- 确定性预检

/// 玩家ID 预检。返回 `Some(错误响应)` = 可确定拒绝；`None` = 交给助手定夺。
///
/// 只覆盖能确定性判定的情形：缺字段 / null → `int(None)` 必抛（“格式错误”）；
/// 整数越界 → 必抛“超出范围”。字符串/浮点等**一律放行**（Python `int()`
/// 接受全角数字、空白包裹、浮点截断等边角语义，交给助手保持逐字一致）。
pub fn precheck_userid(v: Option<&Value>) -> Option<(StatusCode, Json<Value>)> {
    match v {
        None | Some(Value::Null) => Some(err(400, "玩家ID格式错误")),
        Some(Value::Number(n)) => match n.as_i64() {
            Some(i) => {
                if i <= 0 || i > MAX_USERID {
                    Some(err(400, "玩家ID超出范围"))
                } else {
                    None
                }
            }
            // 浮点：Python int(x) 向零截断；仅当截断后越界才可确定拒绝
            None => match n.as_f64() {
                Some(f) => {
                    let t = f.trunc();
                    if t <= 0.0 || t > MAX_USERID as f64 {
                        Some(err(400, "玩家ID超出范围"))
                    } else {
                        None
                    }
                }
                None => None,
            },
        },
        // 字符串：Python int("…") 的边角语义（全角/空白/下划线）交给助手
        Some(_) => None,
    }
}

/// 标识符（缩写/模块名）ASCII 白名单：`^[a-z0-9_]{1,64}$`（与 `CpUserData._IDENT_RE` 同）。
fn is_ascii_ident(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 64
        && s.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

/// 缩写预检：空/纯空白 → “缩写不能为空”；trim+lower 后不匹配 ASCII 白名单 →
/// “格式错误”（Python 侧同样用 ASCII 白名单，故可确定）；其余放行。
pub fn precheck_appcode(v: Option<&Value>) -> Option<(StatusCode, Json<Value>)> {
    let s = match v {
        None | Some(Value::Null) => "",
        Some(Value::String(s)) => s.as_str(),
        // 非字符串：Python 侧 `(raw or '').strip()` 对真值非串会抛 AttributeError（500），
        // 不做确定性判断，交助手
        Some(_) => return None,
    };
    let t = s.trim().to_ascii_lowercase();
    if t.is_empty() {
        return Some(err(400, "缩写不能为空"));
    }
    if !is_ascii_ident(&t) {
        return Some(err(400, "缩写格式错误（仅小写字母/数字/下划线）"));
    }
    None
}

/// 模块名预检：trim+lower 后不匹配 ASCII 白名单 → `模块名非法: <原样>`（legacy 文案
/// 里的 `{module}` 是**已 trim+lower** 的值）；其余放行。
pub fn precheck_module(v: Option<&Value>) -> Option<(StatusCode, Json<Value>)> {
    let s = match v {
        None | Some(Value::Null) => "",
        Some(Value::String(s)) => s.as_str(),
        Some(_) => return None,
    };
    let t = s.trim().to_ascii_lowercase();
    if !is_ascii_ident(&t) {
        return Some(err(400, &format!("模块名非法: {t}")));
    }
    None
}

// ---------------------------------------------------------------- 调助手

async fn call(
    state: &AppState,
    action: &str,
    payload: Value,
) -> Result<(StatusCode, Json<Value>)> {
    let root = match state.config_path.parent() {
        Some(p) => p.to_path_buf(),
        None => return Ok(err(500, "无法定位 legacy 目录（助手所在处）")),
    };
    match pybridge::call_helper(&root, HELPER_NAME, action, payload).await {
        Ok(HelperOut::Body(b)) => Ok((StatusCode::OK, Json(b))),
        Ok(HelperOut::Error(status, msg)) => Ok(err(status, &msg)),
        Err((status, msg)) => Ok(err(status, &msg)),
    }
}

/// 六个端点共用的「预检 → 转发」骨架。
async fn dispatch(
    state: &AppState,
    action: &str,
    body: Value,
    checks: Vec<Option<(StatusCode, Json<Value>)>>,
) -> Result<(StatusCode, Json<Value>)> {
    for c in checks.into_iter().flatten() {
        return Ok(c);
    }
    call(state, action, body).await
}

// ---------------------------------------------------------------- 端点

/// `GET/POST /api/cp-data/direct/appcodes` —— 缩写清单（无参数）。
pub async fn appcodes(State(state): State<AppState>) -> Result<(StatusCode, Json<Value>)> {
    call(&state, "appcodes", json!({})).await
}

/// `POST /api/cp-data/direct/modules` —— `{userid, appcode}` → 模块列表。
pub async fn modules(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    dispatch(
        &state,
        "modules",
        body.clone(),
        vec![
            precheck_userid(body.get("userid")),
            precheck_appcode(body.get("appcode")),
        ],
    )
    .await
}

/// `POST /api/cp-data/direct/module` —— `{userid, appcode, module}` → 单模块明细。
pub async fn module(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    dispatch(
        &state,
        "module",
        body.clone(),
        vec![
            precheck_userid(body.get("userid")),
            precheck_appcode(body.get("appcode")),
            precheck_module(body.get("module")),
        ],
    )
    .await
}

/// `POST /api/cp-data/direct/write-prepare` —— 受控写第一步（只读，回吐当前值）。
pub async fn write_prepare(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    dispatch(
        &state,
        "write-prepare",
        body.clone(),
        vec![
            precheck_userid(body.get("userid")),
            precheck_appcode(body.get("appcode")),
            precheck_module(body.get("module")),
        ],
    )
    .await
}

/// `POST /api/cp-data/direct/write` —— 受控写第二步（⚠ 真写；响应 snapshot 可撤回）。
pub async fn write(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    let missing_value = if body.get("value").is_none() {
        Some(err(400, "缺少 value"))
    } else {
        None
    };
    dispatch(
        &state,
        "write",
        body.clone(),
        vec![
            precheck_userid(body.get("userid")),
            precheck_appcode(body.get("appcode")),
            precheck_module(body.get("module")),
            missing_value,
        ],
    )
    .await
}

/// `POST /api/cp-data/direct/clear` —— 清空（⚠ 不可逆、无快照）。
pub async fn clear(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    dispatch(
        &state,
        "clear",
        body.clone(),
        vec![
            precheck_userid(body.get("userid")),
            precheck_appcode(body.get("appcode")),
            precheck_module(body.get("module")),
        ],
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    fn msg(r: Option<(StatusCode, Json<Value>)>) -> Option<(u16, String)> {
        r.map(|(st, j)| {
            (
                st.as_u16(),
                j.0.get("message").and_then(Value::as_str).unwrap_or("").to_string(),
            )
        })
    }

    /// userid 预检矩阵：只拦「必抛」的情形，能成功的（含字符串/浮点）放行给助手。
    #[rstest]
    #[case(None, Some((400, "玩家ID格式错误")))]
    #[case(Some(json!(null)), Some((400, "玩家ID格式错误")))]
    #[case(Some(json!(0)), Some((400, "玩家ID超出范围")))]
    #[case(Some(json!(-5)), Some((400, "玩家ID超出范围")))]
    #[case(Some(json!(2147483648i64)), Some((400, "玩家ID超出范围")))]
    #[case::ok_min(Some(json!(1)), None)]
    #[case::ok_max(Some(json!(2147483647i64)), None)]
    #[case::ok_typical(Some(json!(1040720)), None)]
    // 字符串/浮点放行（Python int() 的边角语义交给助手，避免两侧漂移）
    #[case::str_forward(Some(json!("1040720")), None)]
    #[case::str_bad_forward(Some(json!("abc")), None)]
    #[case::float_forward(Some(json!(1040720.9)), None)]
    #[case::float_oor(Some(json!(1e12)), Some((400, "玩家ID超出范围")))]
    fn test_precheck_userid_matrix(
        #[case] v: Option<Value>,
        #[case] expect: Option<(u16, &str)>,
    ) {
        let got = msg(precheck_userid(v.as_ref()));
        assert_eq!(got, expect.map(|(s, m)| (s, m.to_string())));
    }

    /// 缩写预检矩阵。
    #[rstest]
    #[case::absent(None, Some((400, "缩写不能为空")))]
    #[case::null(Some(json!(null)), Some((400, "缩写不能为空")))]
    #[case::empty(Some(json!("")), Some((400, "缩写不能为空")))]
    #[case::spaces(Some(json!("   ")), Some((400, "缩写不能为空")))]
    #[case::upper_ok(Some(json!("XZMP")), None)]
    #[case::trim_ok(Some(json!(" xzmp ")), None)]
    #[case::ok(Some(json!("xzmp")), None)]
    #[case::underscore_ok(Some(json!("a_b9")), None)]
    #[case::dash(Some(json!("xz-mp")), Some((400, "缩写格式错误（仅小写字母/数字/下划线）")))]
    #[case::chinese(Some(json!("川麻")), Some((400, "缩写格式错误（仅小写字母/数字/下划线）")))]
    #[case::too_long(Some(json!("a".repeat(65))), Some((400, "缩写格式错误（仅小写字母/数字/下划线）")))]
    fn test_precheck_appcode_matrix(#[case] v: Option<Value>, #[case] expect: Option<(u16, &str)>) {
        let got = msg(precheck_appcode(v.as_ref()));
        assert_eq!(got, expect.map(|(s, m)| (s, m.to_string())));
    }

    /// 模块名预检矩阵：文案里带的是 trim+lower 后的值。
    #[rstest]
    #[case::absent(None, Some((400, "模块名非法: ")))]
    #[case::empty(Some(json!("")), Some((400, "模块名非法: ")))]
    #[case::ok(Some(json!("award")), None)]
    #[case::upper_ok(Some(json!("AWARD")), None)]
    #[case::dash(Some(json!("bad-module")), Some((400, "模块名非法: bad-module")))]
    #[case::upper_dash(Some(json!("Bad-Module")), Some((400, "模块名非法: bad-module")))]
    fn test_precheck_module_matrix(#[case] v: Option<Value>, #[case] expect: Option<(u16, &str)>) {
        let got = msg(precheck_module(v.as_ref()));
        assert_eq!(got, expect.map(|(s, m)| (s, m.to_string())));
    }

    /// 64 字符边界：64 通过、65 拒（与 `_IDENT_RE{1,64}` 一致）。
    #[test]
    fn test_ident_length_boundary() {
        assert!(is_ascii_ident(&"a".repeat(64)));
        assert!(!is_ascii_ident(&"a".repeat(65)));
        assert!(!is_ascii_ident(""));
    }

    /// `write` 缺 value 的文案（与 legacy `缺少 value` 一致）。
    #[test]
    fn test_write_missing_value_message() {
        let body = json!({"userid": 1040720, "appcode": "xzmp", "module": "award"});
        assert!(body.get("value").is_none());
        let (st, j) = err(400, "缺少 value");
        assert_eq!(st.as_u16(), 400);
        assert_eq!(j.0.get("message").and_then(Value::as_str), Some("缺少 value"));
        assert_eq!(j.0.get("success").and_then(Value::as_bool), Some(false));
    }
}
