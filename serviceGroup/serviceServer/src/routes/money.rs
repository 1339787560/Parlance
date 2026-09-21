//! 货币与礼包 (`/api/set-*` + `/api/query-costume`) —— U3 迁移 (2026-09-22)。
//!
//! 迁移自 legacy `CustomRoute/ServiceRoute.py` 的 8 条端点，分两类实现：
//!
//! **A) 纯 Rust**
//!   - `/api/set-gold`      起 `exeDir/RobotToolD.exe`（stdin 传子命令，3s 超时 kill），
//!                          对齐 legacy「起线程 + 立即返」的 fire-and-forget 语义；
//!   - `/api/set-points`    转发内网 deposit `:5003/setscore`（积分）；
//!   - `/api/set-silver`    转发内网 deposit `:5003/SetSilver`（银两）。
//!     远端只认单 userid（逗号串会静默 500），故按 uid **拆单逐个调用**再聚合
//!     （legacy `_proxy_deposit_multi` 同语义）；伪装 UA/Origin/Referer 绕 WAF。
//!
//! **B) Rust 校验 + Python 助手**
//!   - `/api/set-tqvip` / `set-weekcard` / `set-monthcard` / `query-costume` /
//!     `set-newplayer-gift`：数据层在 Python CommonTools（游戏库 + protobuf + 凭据解密），
//!     经 `luaDataTool.py` 子进程（契约见该文件头）。不引 mysql/redis/protobuf 依赖、
//!     不二次实现凭据与 protobuf，数据路径与 legacy 完全一致（同 `spideorder.rs` 起
//!     `python spideOnlineLog.py` 的既有做法）。
//!
//! **校验文案与状态码逐条对齐 legacy**；助手侧仍保留同套校验（它也可独立 CLI 运行），
//! 故「格式类」校验（如日期字符串）以助手为准、Rust 先拦廉价项以免白起子进程。

use crate::error::Result;
use crate::state::AppState;
use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use serde_json::{json, Value};
use std::process::Stdio;
use std::time::Duration;

/// 内网 deposit 远程（legacy 硬编码；env 可覆盖，便于换环境/测试）。
const DEPOSIT_REMOTE_DEFAULT: &str = "http://192.168.105.62:5003";
/// 伪装 Referer/Origin 用的本机 origin（绕 WAF，对齐 legacy `SERVICESVR_ORIGIN`）。
const SERVICESVR_ORIGIN: &str = "http://localhost:5000";
/// 浏览器 UA（对齐 legacy；105.62 拦 Python-urllib 默认 UA → 返 500 HTML）。
const BROWSER_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
                          (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
/// 单个 uid 的转发超时（legacy `timeout=5`）。
const DEPOSIT_TIMEOUT: Duration = Duration::from_secs(5);
/// RobotToolD.exe 单次命令超时（legacy `communicate(timeout=3)`）。
const GOLD_TIMEOUT: Duration = Duration::from_secs(3);
/// 助手解释器（默认走 PATH —— 与 legacy 同源；env 可钉定，如 D:\Compiler\python\python.exe）。
const PYTHON_DEFAULT: &str = "python";
/// 助手脚本名（与 `serviceServer-legacy/` 同目录，随发布包发布）。
const HELPER_NAME: &str = "luaDataTool.py";
/// 助手整体超时（DB 慢查询留足余量）。
const HELPER_TIMEOUT: Duration = Duration::from_secs(60);

fn err(status: u16, msg: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_REQUEST),
        Json(json!({ "success": false, "message": msg })),
    )
}

fn ok(body: Value) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(body))
}

/// Python 值语义的「truthy」：None / 空串 / 0 / false 视为假。
/// 用于复刻 legacy `if not operation or not gold_count` 这类判定。
fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Number(n)) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Some(Value::Bool(b)) => *b,
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// Python `int()` 语义（接受数字与可解析字符串）。
fn py_int(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().map(|f| f as i64)),
        Value::String(s) => s.trim().parse::<i64>().ok(),
        Value::Bool(b) => Some(if *b { 1 } else { 0 }),
        _ => None,
    }
}

// ---------- 校验（纯函数，逐条对齐 legacy 文案） ----------

/// `/api/set-gold` 校验：返回 (operation, goldCount)。
pub fn validate_gold(body: &Value) -> std::result::Result<(String, i64), (u16, String)> {
    let operation = body.get("operation");
    let gold = body.get("goldCount");
    if !truthy(operation) || !truthy(gold) {
        return Err((400, "参数不完整".into()));
    }
    let operation = operation.and_then(Value::as_str).unwrap_or("").to_string();
    let count = match gold.and_then(py_int) {
        Some(n) => n,
        None => return Err((400, "金币数量格式错误".into())),
    };
    if count <= 0 {
        return Err((400, "金币数量必须为正整数".into()));
    }
    Ok((operation, count))
}

/// 构造 RobotToolD.exe 子命令；userId/userIds 非法时返回 None
/// （legacy 在**线程内**静默 return，HTTP 早已 200 —— 这里保持一致）。
pub fn gold_command(operation: &str, body: &Value, count: i64) -> Option<String> {
    match operation {
        "single" => {
            let uid = body.get("userId").and_then(py_int)?;
            if uid <= 0 {
                return None;
            }
            Some(format!("setSingleGold {uid} {count}"))
        }
        "multi" => {
            let ids = body.get("userIds")?.as_array()?;
            let valid: Vec<String> = ids
                .iter()
                .filter_map(py_int)
                .filter(|n| *n > 0)
                .map(|n| n.to_string())
                .collect();
            if valid.is_empty() {
                return None;
            }
            Some(format!("setMultiGold {} {count}", valid.join(" ")))
        }
        _ => None,
    }
}

/// deposit 远程转发的入参校验（对齐 legacy `_validate_deposit_payload`）。
/// 返回 (userIds 字符串列表, count, gameid, opid)。
pub fn validate_deposit(body: &Value) -> std::result::Result<(Vec<String>, i64, i64, Option<i64>), (u16, String)> {
    let ids = body.get("userIds").and_then(Value::as_array).cloned().unwrap_or_default();
    if ids.is_empty() {
        return Err((400, "userIds 必填且非空".into()));
    }
    let count = match body.get("count") {
        None | Some(Value::Null) => return Err((400, "count 必填".into())),
        Some(v) => match py_int(v) {
            Some(n) => n,
            None => return Err((400, "count 格式错误".into())),
        },
    };
    if count <= 0 {
        return Err((400, "count 必须为正整数".into()));
    }
    let valid: Vec<String> = ids
        .iter()
        .filter_map(py_int)
        .filter(|n| *n > 0)
        .map(|n| n.to_string())
        .collect();
    if valid.is_empty() {
        return Err((400, "无有效 userId".into()));
    }
    let gameid = match body.get("gameid") {
        None | Some(Value::Null) => 283, // 川麻 xzmo 默认（legacy 硬编码 283）
        Some(v) => match py_int(v) {
            Some(n) => n,
            None => return Err((500, "gameid 格式错误".into())),
        },
    };
    let opid = match body.get("opid") {
        None | Some(Value::Null) => None,
        Some(v) => match py_int(v) {
            Some(n) => Some(n),
            None => return Err((500, "opid 格式错误".into())),
        },
    };
    Ok((valid, count, gameid, opid))
}

/// `/api/set-tqvip` 校验。
pub fn validate_tqvip(body: &Value) -> std::result::Result<(), (u16, String)> {
    let has = |k: &str| body.get(k).map(|v| !v.is_null()).unwrap_or(false);
    if !truthy(body.get("userIds"))
        || !has("experience")
        || !has("lastLoginDate")
        || !has("isdemoteani")
    {
        return Err((400, "参数不完整".into()));
    }
    // 日期格式（字符串）由助手判定并回 400「上次登录时间格式错误」；这里只拦经验值。
    match body.get("experience").and_then(py_int) {
        Some(n) if n >= 0 => Ok(()),
        _ => Err((400, "经验值必须是非负整数".into())),
    }
}

/// `/api/set-weekcard` / `/api/set-monthcard` 校验（legacy 只查参数齐备）。
pub fn validate_card(body: &Value) -> std::result::Result<(), (u16, String)> {
    if !truthy(body.get("userIds")) || body.get("days").map(Value::is_null).unwrap_or(true) {
        return Err((400, "参数不完整".into()));
    }
    Ok(())
}

/// `/api/query-costume` 校验：返回 userId。
pub fn validate_costume(body: &Value) -> std::result::Result<i64, (u16, String)> {
    if !truthy(body.get("userId")) {
        return Err((400, "参数不完整".into()));
    }
    match body.get("userId").and_then(py_int) {
        Some(n) if n > 0 => Ok(n),
        _ => Err((400, "玩家ID格式错误".into())),
    }
}

/// `/api/set-newplayer-gift` 校验。
pub fn validate_gift(body: &Value) -> std::result::Result<(), (u16, String)> {
    let is_list = body.get("userIds").map(Value::is_array).unwrap_or(false);
    if !is_list || !truthy(body.get("userIds")) {
        return Err((400, "参数不完整".into()));
    }
    // legacy 会在此处静默过滤非法 uid，全非法才报错
    let valid = body
        .get("userIds")
        .and_then(Value::as_array)
        .map(|a| a.iter().filter_map(py_int).filter(|n| *n > 0).count())
        .unwrap_or(0);
    if valid == 0 {
        return Err((400, "请输入有效的玩家ID列表".into()));
    }
    let cancel = body.get("cancel").and_then(Value::as_bool).unwrap_or(false);
    if cancel {
        return Ok(());
    }
    match body.get("receivableDay") {
        Some(v) if !v.is_null() => match py_int(v) {
            Some(d) if (1..=7).contains(&d) => Ok(()),
            _ => Err((400, "可领天数必须是 1-7 的整数".into())),
        },
        _ => {
            if body.get("receivedays").map(Value::is_null).unwrap_or(true) {
                return Err((400, "参数不完整".into()));
            }
            match body.get("receivedays").and_then(py_int) {
                Some(d) if (0..=7).contains(&d) => Ok(()),
                _ => Err((400, "领取天数必须是 0-7 的整数".into())),
            }
        }
    }
}

// ---------- A) 纯 Rust 端点 ----------

/// POST /api/set-gold —— 起 RobotToolD.exe（fire-and-forget，与 legacy 同语义）。
pub async fn set_gold(State(state): State<AppState>, Json(body): Json<Value>) -> Result<(StatusCode, Json<Value>)> {
    let (operation, count) = match validate_gold(&body) {
        Ok(v) => v,
        Err((s, m)) => return Ok(err(s, &m)),
    };
    let exe_dir = match state.config_path.parent() {
        Some(p) => p.join("exeDir"),
        None => return Ok(err(400, "RobotToolD.exe不存在")),
    };
    let exe_path = exe_dir.join("RobotToolD.exe");
    if !exe_path.exists() {
        return Ok(err(400, "RobotToolD.exe不存在"));
    }
    // 与 legacy 一致：先回「已提交」，实际执行放后台线程（内部失败只进日志）
    if let Some(cmd) = gold_command(&operation, &body, count) {
        tokio::task::spawn_blocking(move || run_robot_tool(&exe_dir, &cmd));
    } else {
        tracing::warn!("set-gold: operation={operation} 的 userId(s) 非法，已忽略（对齐 legacy 静默）");
    }
    Ok(ok(json!({
        "success": true,
        "message": format!("金币设置请求已提交，操作类型: {operation}"),
    })))
}

/// 跑一次 RobotToolD.exe：命令走 stdin，超时 kill（对齐 legacy communicate(timeout=3)）。
fn run_robot_tool(exe_dir: &std::path::Path, command: &str) {
    use std::io::Write;
    let mut child = match std::process::Command::new(exe_dir.join("RobotToolD.exe"))
        .current_dir(exe_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            tracing::warn!("set-gold: 启动 RobotToolD.exe 失败: {e}");
            return;
        }
    };
    if let Some(stdin) = child.stdin.as_mut() {
        let _ = stdin.write_all(format!("{command}\n").as_bytes());
    }
    // 关掉 stdin，进程才会读到 EOF
    drop(child.stdin.take());
    let deadline = std::time::Instant::now() + GOLD_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(st)) => {
                tracing::info!("set-gold 完成 (cmd={command}) exit={:?}", st.code());
                return;
            }
            Ok(None) => {
                if std::time::Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    tracing::warn!("set-gold 超时 kill (cmd={command})");
                    return;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(e) => {
                tracing::warn!("set-gold 等待失败 (cmd={command}): {e}");
                return;
            }
        }
    }
}

/// POST /api/set-points —— 积分：转发 deposit `/setscore`。
pub async fn set_points(State(state): State<AppState>, Json(body): Json<Value>) -> Result<(StatusCode, Json<Value>)> {
    deposit_proxy(&state, "/setscore", 0, body).await
}

/// POST /api/set-silver —— 银两：转发 deposit `/SetSilver`（默认 opid=2 游戏内）。
pub async fn set_silver(State(state): State<AppState>, Json(body): Json<Value>) -> Result<(StatusCode, Json<Value>)> {
    deposit_proxy(&state, "/SetSilver", 2, body).await
}

/// 逐个 uid 转发并聚合（远端仅支持单 uid）。
async fn deposit_proxy(
    state: &AppState,
    endpoint: &str,
    default_opid: i64,
    body: Value,
) -> Result<(StatusCode, Json<Value>)> {
    let (user_ids, count, gameid, opid) = match validate_deposit(&body) {
        Ok(v) => v,
        Err((s, m)) => return Ok(err(s, &m)),
    };
    let opid = opid.unwrap_or(default_opid);
    let remote = std::env::var("SERVICESVR_DEPOSIT_REMOTE").unwrap_or_else(|_| DEPOSIT_REMOTE_DEFAULT.into());
    let url = format!("{}{}", remote.trim_end_matches('/'), endpoint);

    let mut results = Vec::new();
    let mut all_ok = true;
    for uid in &user_ids {
        let (value, status) = forward_one(&state.http_client, &url, uid, count, gameid, opid).await;
        let ok = status == 200;
        if !ok {
            all_ok = false;
        }
        let mut item = json!({ "userId": uid, "status": status, "ok": ok });
        if !ok {
            item["upstream"] = value;
        }
        results.push(item);
    }
    let code = if all_ok { StatusCode::OK } else { StatusCode::INTERNAL_SERVER_ERROR };
    Ok((
        code,
        Json(json!({
            "success": all_ok,
            "results": results,
            "userIds": user_ids.join(","),
            "count": count,
            "opid": opid,
        })),
    ))
}

/// 单次转发：返 (upstream 描述, HTTP 状态)。连接不通 → 502 + reachable:false。
async fn forward_one(
    client: &reqwest::Client,
    url: &str,
    uid: &str,
    count: i64,
    gameid: i64,
    opid: i64,
) -> (Value, u16) {
    // 字段全为整数，无需 urlencode
    let form = format!("userid={uid}&count={count}&gameid={gameid}&opid={opid}");
    let sent = client
        .post(url)
        .header(reqwest::header::CONTENT_TYPE, "application/x-www-form-urlencoded")
        .header(reqwest::header::USER_AGENT, BROWSER_UA)
        .header(reqwest::header::ACCEPT, "*/*")
        .header(reqwest::header::ORIGIN, SERVICESVR_ORIGIN)
        .header(reqwest::header::REFERER, format!("{SERVICESVR_ORIGIN}/deposit"))
        .body(form)
        .timeout(DEPOSIT_TIMEOUT)
        .send()
        .await;
    match sent {
        Ok(resp) => {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            let parsed = serde_json::from_str::<Value>(&body).unwrap_or_else(|_| json!({ "raw": body }));
            if status == 200 {
                (parsed, 200)
            } else {
                (
                    json!({
                        "error": format!("HTTP {status}"),
                        "reachable": true,
                        "upstream_status": status,
                        "body": parsed,
                        "url": url,
                    }),
                    status,
                )
            }
        }
        Err(e) => {
            let reachable = !(e.is_timeout() || e.is_connect() || e.is_request());
            (
                json!({ "error": format!("{e}"), "reachable": reachable, "url": url }),
                502,
            )
        }
    }
}

// ---------- B) Rust 校验 + Python 助手 ----------

/// POST /api/set-tqvip —— 荣耀特权。
pub async fn set_tqvip(State(state): State<AppState>, Json(body): Json<Value>) -> Result<(StatusCode, Json<Value>)> {
    if let Err((s, m)) = validate_tqvip(&body) {
        return Ok(err(s, &m));
    }
    helper_response(&state, "set-tqvip", body).await
}

/// POST /api/set-weekcard —— 周卡。
pub async fn set_weekcard(State(state): State<AppState>, Json(body): Json<Value>) -> Result<(StatusCode, Json<Value>)> {
    if let Err((s, m)) = validate_card(&body) {
        return Ok(err(s, &m));
    }
    helper_response(&state, "set-weekcard", body).await
}

/// POST /api/set-monthcard —— 月卡。
pub async fn set_monthcard(State(state): State<AppState>, Json(body): Json<Value>) -> Result<(StatusCode, Json<Value>)> {
    if let Err((s, m)) = validate_card(&body) {
        return Ok(err(s, &m));
    }
    helper_response(&state, "set-monthcard", body).await
}

/// POST /api/query-costume —— 查装扮（只读）。
pub async fn query_costume(State(state): State<AppState>, Json(body): Json<Value>) -> Result<(StatusCode, Json<Value>)> {
    if let Err((s, m)) = validate_costume(&body) {
        return Ok(err(s, &m));
    }
    helper_response(&state, "query-costume", body).await
}

/// POST /api/set-newplayer-gift —— 迎新礼包。
pub async fn set_newplayer_gift(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    if let Err((s, m)) = validate_gift(&body) {
        return Ok(err(s, &m));
    }
    helper_response(&state, "set-newplayer-gift", body).await
}

/// 调 `luaDataTool.py`：参数 JSON 走 stdin，结果 JSON 走 stdout（契约见脚本头）。
async fn helper_response(
    state: &AppState,
    action: &str,
    body: Value,
) -> Result<(StatusCode, Json<Value>)> {
    match call_helper(state, action, body).await {
        Ok(HelperOut::Body(b)) => Ok((StatusCode::OK, Json(b))),
        Ok(HelperOut::Error(status, msg)) => Ok(err(status, &msg)),
        Err((status, msg)) => Ok(err(status, &msg)),
    }
}

enum HelperOut {
    /// 成功：原 Flask 响应体（含 success/message/results…）
    Body(Value),
    /// 失败：状态码 + 文案
    Error(u16, String),
}

async fn call_helper(
    state: &AppState,
    action: &str,
    body: Value,
) -> std::result::Result<HelperOut, (u16, String)> {
    let dir = state
        .config_path
        .parent()
        .map(|p| p.to_path_buf())
        .ok_or((500, "无法定位 legacy 目录".to_string()))?;
    let python = std::env::var("SERVICESVR_PYTHON").unwrap_or_else(|_| PYTHON_DEFAULT.to_string());
    let payload = body.to_string();
    let action = action.to_string();

    let task = tokio::task::spawn_blocking(move || -> std::result::Result<std::process::Output, String> {
        use std::io::Write;
        let mut child = std::process::Command::new(&python)
            .arg(HELPER_NAME)
            .arg(&action)
            .current_dir(&dir)
            // 管道下 Python 默认可能落到 ANSI 代码页 → 中文 JSON 变非 UTF-8，显式钉死
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("启动助手失败 (python={python}): {e}"))?;
        if let Some(stdin) = child.stdin.as_mut() {
            stdin
                .write_all(payload.as_bytes())
                .map_err(|e| format!("写入助手 stdin 失败: {e}"))?;
        }
        drop(child.stdin.take());
        child.wait_with_output().map_err(|e| format!("等待助手失败: {e}"))
    });

    let out = match tokio::time::timeout(HELPER_TIMEOUT, task).await {
        Ok(Ok(Ok(o))) => o,
        Ok(Ok(Err(e))) => return Err((500, e)),
        Ok(Err(e)) => return Err((500, format!("助手任务失败: {e}"))),
        Err(_) => return Err((500, format!("助手超时 (>{HELPER_TIMEOUT:?})"))),
    };

    // 严格 UTF-8：失败说明编码没对齐（比默默替换字符更早暴露）
    let stdout = match std::str::from_utf8(&out.stdout) {
        Ok(s) => s.trim(),
        Err(e) => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            return Err((
                500,
                format!("助手输出不是 UTF-8 ({e})；stderr: {}", truncate(&stderr, 300)),
            ));
        }
    };
    let parsed: Value = match serde_json::from_str(stdout) {
        Ok(v) => v,
        Err(e) => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            return Err((
                500,
                format!(
                    "助手返回无法解析为 JSON: {e}；stdout: {}；stderr: {}",
                    truncate(stdout, 200),
                    truncate(&stderr, 300)
                ),
            ));
        }
    };
    if parsed.get("ok").and_then(Value::as_bool) == Some(true) {
        Ok(HelperOut::Body(parsed.get("body").cloned().unwrap_or(Value::Null)))
    } else {
        let status = parsed.get("status").and_then(Value::as_u64).unwrap_or(500) as u16;
        let msg = parsed
            .get("message")
            .and_then(Value::as_str)
            .unwrap_or("助手执行失败")
            .to_string();
        Ok(HelperOut::Error(status, msg))
    }
}

fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        return s.to_string();
    }
    s.chars().take(n).collect::<String>() + "…"
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::json;

    // ---- set-gold ----

    #[test]
    fn test_validate_gold_ok_and_messages() {
        assert_eq!(
            validate_gold(&json!({"operation": "single", "goldCount": 100})).unwrap(),
            ("single".to_string(), 100)
        );
        // 字符串数字也接受（Python int() 语义）
        assert_eq!(
            validate_gold(&json!({"operation": "multi", "goldCount": "50"})).unwrap(),
            ("multi".to_string(), 50)
        );
        // 缺参 / 空串 / 0 → 参数不完整（对齐 `not gold_count`）
        assert_eq!(validate_gold(&json!({})).unwrap_err(), (400, "参数不完整".into()));
        assert_eq!(
            validate_gold(&json!({"operation": "single", "goldCount": ""})).unwrap_err(),
            (400, "参数不完整".into())
        );
        assert_eq!(
            validate_gold(&json!({"operation": "single", "goldCount": 0})).unwrap_err(),
            (400, "参数不完整".into())
        );
        // 负 / 非数字
        assert_eq!(
            validate_gold(&json!({"operation": "single", "goldCount": -5})).unwrap_err(),
            (400, "金币数量必须为正整数".into())
        );
        assert_eq!(
            validate_gold(&json!({"operation": "single", "goldCount": "abc"})).unwrap_err(),
            (400, "金币数量格式错误".into())
        );
    }

    #[test]
    fn test_gold_command_single_and_multi() {
        assert_eq!(
            gold_command("single", &json!({"userId": "123"}), 9).as_deref(),
            Some("setSingleGold 123 9")
        );
        // 非法 uid → None（legacy 线程内静默 return）
        assert!(gold_command("single", &json!({"userId": 0}), 9).is_none());
        assert!(gold_command("single", &json!({}), 9).is_none());
        // multi 过滤非法项
        assert_eq!(
            gold_command("multi", &json!({"userIds": [1, "x", 2, -3, 4]}), 7).as_deref(),
            Some("setMultiGold 1 2 4 7")
        );
        assert!(gold_command("multi", &json!({"userIds": ["x", -1]}), 7).is_none());
        // 未知 operation → None
        assert!(gold_command("bulk", &json!({"userId": 1}), 1).is_none());
    }

    // ---- deposit 转发校验 ----

    #[test]
    fn test_validate_deposit_ok_defaults() {
        let (ids, count, gameid, opid) =
            validate_deposit(&json!({"userIds": [1, "2", 3], "count": 100})).unwrap();
        assert_eq!(ids, vec!["1", "2", "3"]);
        assert_eq!(count, 100);
        assert_eq!(gameid, 283, "gameid 缺省 = 283 (川麻 xzmo)");
        assert_eq!(opid, None);
    }

    #[test]
    fn test_validate_deposit_filters_and_overrides() {
        let (ids, _, gameid, opid) = validate_deposit(&json!({
            "userIds": [0, -1, "x", 7],
            "count": 5,
            "gameid": 105,
            "opid": 2,
        }))
        .unwrap();
        assert_eq!(ids, vec!["7"], "非法 uid 静默过滤");
        assert_eq!(gameid, 105);
        assert_eq!(opid, Some(2));
    }

    #[rstest]
    #[case::no_ids(json!({"count": 1}), "userIds 必填且非空")]
    #[case::empty_ids(json!({"userIds": [], "count": 1}), "userIds 必填且非空")]
    #[case::no_count(json!({"userIds": [1]}), "count 必填")]
    #[case::bad_count(json!({"userIds": [1], "count": "x"}), "count 格式错误")]
    #[case::zero_count(json!({"userIds": [1], "count": 0}), "count 必须为正整数")]
    #[case::all_invalid_ids(json!({"userIds": [0, -1], "count": 1}), "无有效 userId")]
    fn test_validate_deposit_errors(#[case] body: Value, #[case] expected: &str) {
        assert_eq!(validate_deposit(&body).unwrap_err(), (400, expected.to_string()));
    }

    // ---- set-tqvip / card / costume / gift ----

    #[test]
    fn test_validate_tqvip_matrix() {
        let good = json!({"userIds":[1],"experience":100,"lastLoginDate":20260101,"isdemoteani":0});
        assert!(validate_tqvip(&good).is_ok());
        assert_eq!(
            validate_tqvip(&json!({"userIds":[1],"experience":100,"lastLoginDate":1})).unwrap_err(),
            (400, "参数不完整".into())
        );
        assert_eq!(
            validate_tqvip(&json!({"userIds":[],"experience":1,"lastLoginDate":1,"isdemoteani":0})).unwrap_err(),
            (400, "参数不完整".into())
        );
        assert_eq!(
            validate_tqvip(&json!({"userIds":[1],"experience":-1,"lastLoginDate":1,"isdemoteani":0})).unwrap_err(),
            (400, "经验值必须是非负整数".into())
        );
        assert_eq!(
            validate_tqvip(&json!({"userIds":[1],"experience":"x","lastLoginDate":1,"isdemoteani":0})).unwrap_err(),
            (400, "经验值必须是非负整数".into())
        );
        // 日期格式交给助手；此处只确保不拦（非法日期会在助手侧回 400）
        assert!(validate_tqvip(&json!({
            "userIds":[1],"experience":0,"lastLoginDate":"bad-date","isdemoteani":0
        }))
        .is_ok());
    }

    #[test]
    fn test_validate_card_matrix() {
        assert!(validate_card(&json!({"userIds":[1],"days":30})).is_ok());
        assert_eq!(
            validate_card(&json!({"userIds":[1]})).unwrap_err(),
            (400, "参数不完整".into())
        );
        assert_eq!(
            validate_card(&json!({"days":30})).unwrap_err(),
            (400, "参数不完整".into())
        );
    }

    #[test]
    fn test_validate_costume_matrix() {
        assert_eq!(validate_costume(&json!({"userId": 123})).unwrap(), 123);
        assert_eq!(validate_costume(&json!({"userId": "123"})).unwrap(), 123);
        assert_eq!(
            validate_costume(&json!({})).unwrap_err(),
            (400, "参数不完整".into())
        );
        // 数字 0 → Python falsy → 走「参数不完整」（对齐 `if not user_id`）
        assert_eq!(
            validate_costume(&json!({"userId": 0})).unwrap_err(),
            (400, "参数不完整".into())
        );
        // 字符串 "0" → 非空串是 truthy → 进 int() 后 <=0 → 「玩家ID格式错误」
        assert_eq!(
            validate_costume(&json!({"userId": "0"})).unwrap_err(),
            (400, "玩家ID格式错误".into())
        );
        assert_eq!(
            validate_costume(&json!({"userId": "abc"})).unwrap_err(),
            (400, "玩家ID格式错误".into())
        );
    }

    #[test]
    fn test_validate_gift_matrix() {
        // cancel 模式
        assert!(validate_gift(&json!({"userIds":[1],"cancel":true})).is_ok());
        // receivedays 模式
        assert!(validate_gift(&json!({"userIds":[1],"receivedays":3})).is_ok());
        assert!(validate_gift(&json!({"userIds":[1],"receivedays":0})).is_ok());
        // receivableDay 模式（第 X 天可领）
        assert!(validate_gift(&json!({"userIds":[1],"receivableDay":1})).is_ok());
        assert!(validate_gift(&json!({"userIds":[1],"receivableDay":7})).is_ok());

        assert_eq!(
            validate_gift(&json!({})).unwrap_err(),
            (400, "参数不完整".into())
        );
        assert_eq!(
            validate_gift(&json!({"userIds":"1"})).unwrap_err(),
            (400, "参数不完整".into())
        );
        assert_eq!(
            validate_gift(&json!({"userIds":[0]})).unwrap_err(),
            (400, "请输入有效的玩家ID列表".into())
        );
        assert_eq!(
            validate_gift(&json!({"userIds":[1],"receivableDay":9})).unwrap_err(),
            (400, "可领天数必须是 1-7 的整数".into())
        );
        assert_eq!(
            validate_gift(&json!({"userIds":[1],"receivableDay":0})).unwrap_err(),
            (400, "可领天数必须是 1-7 的整数".into())
        );
        // 两个模式都没给
        assert_eq!(
            validate_gift(&json!({"userIds":[1]})).unwrap_err(),
            (400, "参数不完整".into())
        );
        assert_eq!(
            validate_gift(&json!({"userIds":[1],"receivedays":8})).unwrap_err(),
            (400, "领取天数必须是 0-7 的整数".into())
        );
    }

    // ---- 助手输出解析（不真起进程的部分） ----

    #[test]
    fn test_py_int_semantics() {
        assert_eq!(py_int(&json!(5)), Some(5));
        assert_eq!(py_int(&json!("5")), Some(5));
        assert_eq!(py_int(&json!(" 5 ")), Some(5));
        assert_eq!(py_int(&json!(true)), Some(1));
        assert_eq!(py_int(&json!("x")), None);
        assert_eq!(py_int(&json!(null)), None);
        assert_eq!(py_int(&json!([1])), None);
    }

    #[test]
    fn test_truthy_matches_python_falsy() {
        assert!(!truthy(None));
        assert!(!truthy(Some(&json!(null))));
        assert!(!truthy(Some(&json!(""))));
        assert!(!truthy(Some(&json!(0))));
        assert!(!truthy(Some(&json!(false))));
        assert!(!truthy(Some(&json!([]))));
        assert!(truthy(Some(&json!("x"))));
        assert!(truthy(Some(&json!(1))));
        assert!(truthy(Some(&json!([1]))));
    }
}
