//! 启动序列 (script.json) 四路由 —— U1 序列迁移 (2026-09-21)。
//!
//! 迁移自 legacy `CustomRoute/SequenceRoute.py` (9.6 KB):
//!   GET  /api/script/get-all       -> {success, scripts:[...]}
//!   POST /api/script/save          -> {success, message}          (400 参数不完整)
//!   POST /api/script/execute/:name -> 同步执行序列, {success, message, results}
//!   POST /api/script/execute       -> 异步执行序列, 立即返
//!
//! **存储**: `script.json` 与 `config.json` 同目录。config.yaml 把 SERVICESVR_CONFIG
//! 指向 `serviceServer-legacy/config.json`, 故这里读写的正是 legacy 的同一份文件
//! (与 `services.rs::read_script_order` 的 start-all 口径一致, 不产生第二份真相)。
//!
//! **格式** (两种并存):
//!   新: `{ "scripts": [ { "name", "sequence": [{name,type,exe,display_name}], "created_at" } ] }`
//!   旧: `{ "scripts": { "<name>": { "start_order": [...], "created_at" } } }`
//! get-all 读时把旧格式翻成新格式返回 (不落盘); save 遇 `scripts` 非数组时按 legacy
//! 语义重置为数组。根级其它键 (如 start-all 用的 `start_order`) 原样保留 —— legacy
//! `save_script` 写回的是整个 root 对象, 这里同样不丢键。

use crate::error::{AppError, Result};
use crate::state::AppState;
use axum::extract::Path as UrlPath;
use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// 序列内每个服务启动后的等待 (对齐 legacy `time.sleep(2)`)。
/// 单测注入 `Duration::ZERO` 规避 2s/服务 的真实等待。
const INTER_SERVICE_DELAY: Duration = Duration::from_secs(2);

// ---------- 存储 ----------

/// script.json 路径 = config.json 同目录 (legacy JsonConfigParser 硬编码同目录)。
fn script_path(config_path: &Path) -> PathBuf {
    config_path
        .parent()
        .map(|p| p.join("script.json"))
        .unwrap_or_else(|| PathBuf::from("script.json"))
}

/// 读 script.json。缺文件 -> 空对象 (对齐 legacy `read_script` 返 `{}`);
/// 解析失败 -> Err(中文原因, handler 转 500 文案)。
fn read_script(config_path: &Path) -> std::result::Result<Value, String> {
    match std::fs::read_to_string(script_path(config_path)) {
        Ok(raw) => serde_json::from_str(&raw).map_err(|e| format!("解析 script.json 失败: {e}")),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(json!({})),
        Err(e) => Err(format!("读取 script.json 失败: {e}")),
    }
}

/// 写 script.json: 4 空格缩进 (对齐 legacy `json.dump(indent=4, ensure_ascii=False)`)
/// + 原子写 (tmp+rename)。该文件无下游 ReadDirectoryChangesW 监视, 无需原位写。
fn write_script(path: &Path, script: &Value) -> Result<()> {
    let mut buf = Vec::new();
    let fmt = serde_json::ser::PrettyFormatter::with_indent(b"    ");
    let mut ser = serde_json::Serializer::with_formatter(&mut buf, fmt);
    script.serialize(&mut ser)?;
    crate::atomic_write::atomic_write_bytes(path, &buf)
}

// ---------- 纯函数 (可测) ----------

/// 归一化 `scripts` 为数组: 数组原样返回; 旧格式 (dict) 翻成新格式 (name/sequence/
/// created_at); 缺键或非法 -> 空数组。对齐 legacy `api_get_all_scripts` 的兼容分支。
pub fn scripts_array(script: &Value) -> Vec<Value> {
    match script.get("scripts") {
        Some(Value::Array(arr)) => arr.clone(),
        Some(Value::Object(map)) => map
            .iter()
            .map(|(name, data)| {
                json!({
                    "name": name,
                    "sequence": data.get("start_order").cloned().unwrap_or_else(|| json!([])),
                    "created_at": data.get("created_at").cloned().unwrap_or(Value::Null),
                })
            })
            .collect(),
        _ => Vec::new(),
    }
}

/// 新增或替换同名序列 (legacy `api_save_script` 的更新/追加语义)。
///
/// - `scripts` 非数组 (缺失/旧 dict/非法) -> 重置为 `[]` (对齐 legacy);
/// - 同名已存在 -> 原位替换 (不追加); 否则追加;
/// - root 其它键原样保留。
pub fn upsert_sequence(script: &mut Value, name: &str, start_order: &Value, created_at: &str) {
    if !script.is_object() {
        *script = json!({});
    }
    let obj = script.as_object_mut().expect("root 已归一为对象");
    if !obj.get("scripts").map(Value::is_array).unwrap_or(false) {
        obj.insert("scripts".into(), Value::Array(Vec::new()));
    }
    let arr = obj
        .get_mut("scripts")
        .and_then(Value::as_array_mut)
        .expect("scripts 已归一为数组");
    let new_item = json!({
        "name": name,
        "sequence": start_order.clone(),
        "created_at": created_at,
    });
    match arr
        .iter()
        .position(|it| it.get("name").and_then(Value::as_str) == Some(name))
    {
        Some(idx) => arr[idx] = new_item,
        None => arr.push(new_item),
    }
}

/// 执行一个序列 (阻塞)。返回 `(HTTP 状态码, 响应体)`, 形状对齐 legacy
/// `api_execute_named_sequence`。副作用经 `start` 注入, 故本函数可单测。
///
/// `start(name, type, exe) -> Ok/Err(消息)` 对应 legacy `start_service`。
pub fn run_sequence<F>(
    script: &Value,
    config: &Value,
    sequence_name: &str,
    inter_delay: Duration,
    start: &F,
) -> (StatusCode, Value)
where
    F: Fn(&str, &str, &str) -> std::result::Result<String, String>,
{
    let items = scripts_array(script);
    let item = match items
        .iter()
        .find(|it| it.get("name").and_then(Value::as_str) == Some(sequence_name))
    {
        Some(it) => it,
        None => return not_found(sequence_name),
    };
    // 新格式用 `sequence`; 旧格式条目用 `start_order` (兼容读)。
    let entries = match item
        .get("sequence")
        .or_else(|| item.get("start_order"))
        .and_then(Value::as_array)
    {
        Some(arr) => arr,
        None => return not_found(sequence_name),
    };

    let mut results: Vec<Value> = Vec::new();
    for (i, entry) in entries.iter().enumerate() {
        let (name, svc_type, exe) = match entry {
            Value::Object(o) => (
                o.get("name").and_then(Value::as_str).unwrap_or(""),
                o.get("type").and_then(Value::as_str).unwrap_or(""),
                o.get("exe").and_then(Value::as_str).unwrap_or(""),
            ),
            Value::String(group) => {
                // 旧格式: 条目是服务组名 -> 启动该组下全部服务 (legacy str 分支)。
                let list = match config
                    .get("service")
                    .and_then(|s| s.as_object())
                    .and_then(|s| s.get(group.as_str()))
                    .and_then(Value::as_array)
                {
                    Some(l) => l.clone(),
                    None => {
                        return (
                            StatusCode::BAD_REQUEST,
                            json!({
                                "success": false,
                                "message": format!("服务组 {group} 不存在"),
                                "failed_at": i,
                                "results": results,
                            }),
                        )
                    }
                };
                for s in &list {
                    let t = s.get("type").and_then(Value::as_str).unwrap_or("");
                    let e = s.get("exe").and_then(Value::as_str).unwrap_or("");
                    if t.is_empty() || e.is_empty() {
                        return (
                            StatusCode::INTERNAL_SERVER_ERROR,
                            json!({
                                "success": false,
                                "message": format!("服务组 {group} 的条目缺少 type/exe"),
                                "results": results,
                            }),
                        );
                    }
                    let (success, message) = ok_err(start(group, t, e));
                    results.push(json!({
                        "name": group, "type": t, "success": success, "message": message,
                    }));
                    if !success {
                        return start_failed(i, &format!("{group}_{t}"), &message, results);
                    }
                    sleep_if(inter_delay);
                }
                continue;
            }
            _ => {
                return (
                    StatusCode::BAD_REQUEST,
                    json!({
                        "success": false,
                        "message": format!("序列中第{}个服务的数据格式无效", i + 1),
                        "failed_at": i,
                        "results": results,
                    }),
                )
            }
        };

        if name.is_empty() || svc_type.is_empty() || exe.is_empty() {
            return (
                StatusCode::BAD_REQUEST,
                json!({
                    "success": false,
                    "message": format!("序列中第{}个服务的参数不完整", i + 1),
                    "failed_at": i,
                    "results": results,
                }),
            );
        }
        let (success, message) = ok_err(start(name, svc_type, exe));
        results.push(json!({
            "name": name, "type": svc_type, "success": success, "message": message,
        }));
        if !success {
            return start_failed(i, &format!("{name}_{svc_type}"), &message, results);
        }
        sleep_if(inter_delay);
    }

    (
        StatusCode::OK,
        json!({
            "success": true,
            "message": "所有服务已成功启动",
            "results": results,
        }),
    )
}

fn not_found(sequence_name: &str) -> (StatusCode, Value) {
    (
        StatusCode::NOT_FOUND,
        json!({
            "success": false,
            "message": format!("启动序列 \"{sequence_name}\" 不存在"),
        }),
    )
}

/// 启动失败: legacy 对「启动中途失败」返 **200** + success:false + failed_* 定位字段。
fn start_failed(failed_at: usize, failed_service: &str, message: &str, results: Vec<Value>) -> (StatusCode, Value) {
    (
        StatusCode::OK,
        json!({
            "success": false,
            "message": format!("服务启动失败: {message}"),
            "failed_at": failed_at,
            "failed_service": failed_service,
            "results": results,
        }),
    )
}

fn ok_err(r: std::result::Result<String, String>) -> (bool, String) {
    match r {
        Ok(m) => (true, m),
        Err(m) => (false, m),
    }
}

fn sleep_if(d: Duration) {
    if !d.is_zero() {
        std::thread::sleep(d);
    }
}

/// 生产启动器: 先查服务文件存在 (对齐 legacy `start_service_pywin32` 的前置校验,
/// 给出同款「服务文件不存在: <路径>」文案), 再走 SCM 启动。
fn start_with_path_check(
    abspath: &str,
    name: &str,
    svc_type: &str,
    exe: &str,
) -> std::result::Result<String, String> {
    let service_path = PathBuf::from(abspath).join(name).join(svc_type).join(exe);
    if !service_path.exists() {
        return Err(format!("服务文件不存在: {}", service_path.display()));
    }
    crate::svc_control::imp::start(&format!("{name}_{svc_type}"))
}

fn err400(msg: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::BAD_REQUEST,
        Json(json!({ "success": false, "message": msg })),
    )
}

fn err500(msg: String) -> (StatusCode, Json<Value>) {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({ "success": false, "message": msg })),
    )
}

// ---------- handlers ----------

/// GET /api/script/get-all — 列出全部序列 (旧 dict 格式自动翻新)。
pub async fn get_all(State(state): State<AppState>) -> Result<(StatusCode, Json<Value>)> {
    match read_script(&state.config_path) {
        Ok(script) => Ok((
            StatusCode::OK,
            Json(json!({ "success": true, "scripts": scripts_array(&script) })),
        )),
        Err(e) => Ok(err500(e)),
    }
}

#[derive(Deserialize)]
pub struct SaveReq {
    pub name: Option<String>,
    pub start_order: Option<Value>,
}

/// POST /api/script/save — `{name, start_order}` -> 新增/覆盖同名序列。
pub async fn save(
    State(state): State<AppState>,
    Json(req): Json<SaveReq>,
) -> Result<(StatusCode, Json<Value>)> {
    let name_ok = req.name.as_deref().map(|s| !s.is_empty()).unwrap_or(false);
    // legacy `not start_order`: 空数组也拒 (400)。
    let order_ok = req
        .start_order
        .as_ref()
        .and_then(Value::as_array)
        .map(|a| !a.is_empty())
        .unwrap_or(false);
    if !name_ok || !order_ok {
        return Ok((
            StatusCode::BAD_REQUEST,
            Json(json!({ "success": false, "message": "参数不完整" })),
        ));
    }
    let name = req.name.unwrap_or_default();
    let start_order = req.start_order.unwrap_or(Value::Null);

    let mut script = match read_script(&state.config_path) {
        Ok(s) => s,
        Err(e) => return Ok(err500(format!("保存序列时发生错误: {e}"))),
    };
    upsert_sequence(&mut script, &name, &start_order, &format_local_now());
    match write_script(&script_path(&state.config_path), &script) {
        Ok(()) => Ok((
            StatusCode::OK,
            Json(json!({ "success": true, "message": "序列保存成功" })),
        )),
        Err(e) => Ok(err500(format!("保存序列时发生错误: {e}"))),
    }
}

/// POST /api/script/execute/:name — 同步按序启动序列内全部服务, 全程阻塞。
/// 服务间等待 2s, 故放 spawn_blocking (不占 async runtime 线程)。
pub async fn execute_named(
    State(state): State<AppState>,
    UrlPath(sequence_name): UrlPath<String>,
) -> Result<(StatusCode, Json<Value>)> {
    let script = match read_script(&state.config_path) {
        Ok(s) => s,
        Err(e) => return Ok(err500(format!("执行启动序列时发生错误: {e}"))),
    };
    let config = match crate::routes::read_config_value(&state.config_path) {
        Ok(c) => c,
        Err(e) => return Ok(err500(format!("执行启动序列时发生错误: {e}"))),
    };
    let abspath = state.path_map.abspath();
    let (code, body) = tokio::task::spawn_blocking(move || {
        let start = |n: &str, t: &str, e: &str| start_with_path_check(&abspath, n, t, e);
        run_sequence(&script, &config, &sequence_name, INTER_SERVICE_DELAY, &start)
    })
    .await
    .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
    Ok((code, Json(body)))
}

#[derive(Deserialize)]
pub struct ExecuteReq {
    pub name: Option<String>,
}

/// POST /api/script/execute — 按名异步执行 (立即返, 后台跑完整个序列)。
///
/// 注: legacy 该端点读 `scripts[<name>].start_order` (旧 dict 格式), 而 `save` 早已
/// 只写新数组格式 -> 实际恒 404。这里按新格式判定并按名执行 (同时兼容旧格式),
/// 是 legacy 意图的超集, 无回归面。
pub async fn execute(
    State(state): State<AppState>,
    Json(req): Json<ExecuteReq>,
) -> Result<(StatusCode, Json<Value>)> {
    let name = match req.name {
        Some(n) if !n.is_empty() => n,
        _ => return Ok(err400("请提供序列名称")),
    };
    let script = match read_script(&state.config_path) {
        Ok(s) => s,
        Err(e) => return Ok(err500(e)),
    };
    let exists = scripts_array(&script)
        .iter()
        .any(|it| it.get("name").and_then(Value::as_str) == Some(name.as_str()));
    if !exists {
        return Ok((
            StatusCode::NOT_FOUND,
            Json(json!({ "success": false, "message": format!("序列 {name} 不存在") })),
        ));
    }
    let config = match crate::routes::read_config_value(&state.config_path) {
        Ok(c) => c,
        Err(e) => return Ok(err500(e.to_string())),
    };
    let abspath = state.path_map.abspath();
    let seq = name.clone();
    tokio::task::spawn_blocking(move || {
        let start = |n: &str, t: &str, e: &str| start_with_path_check(&abspath, n, t, e);
        let (_code, body) = run_sequence(&script, &config, &seq, INTER_SERVICE_DELAY, &start);
        tracing::info!("script/execute (async) 序列 {seq}: {body}");
    });
    Ok((
        StatusCode::OK,
        Json(json!({
            "success": true,
            "message": format!("序列 {name} 开始执行，请稍后查看状态"),
        })),
    ))
}

// ---------- 本地时间 (无日期库依赖) ----------

/// 当前本地时间 `YYYY-MM-DD HH:MM:SS` (对齐 legacy `time.strftime`)。
#[cfg(windows)]
pub fn format_local_now() -> String {
    let st = unsafe { windows::Win32::System::SystemInformation::GetLocalTime() };
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond
    )
}

/// 非 Windows 退化: UTC (Mac 无 serviceServer 二进制, 仅保编译与单测)。
#[cfg(not(windows))]
pub fn format_local_now() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    format_epoch_utc(secs)
}

/// epoch 秒 -> `YYYY-MM-DD HH:MM:SS` (UTC)。纯函数, 可测。
/// Windows 生产路径走 `GetLocalTime`, 此函数仅非 Windows 回退与单测使用。
#[cfg_attr(windows, allow(dead_code))]
pub fn format_epoch_utc(secs: i64) -> String {
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (y, m, d) = civil_from_days(days);
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        y,
        m,
        d,
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

/// Howard Hinnant civil_from_days: 1970-01-01 起的天数 -> (年, 月, 日)。
#[cfg_attr(windows, allow(dead_code))]
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64; // [0, 146096]
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    (if m <= 2 { y + 1 } else { y }, m as u32, d)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// 两服务的新格式序列 (与生产 script.json 同形)。
    fn seq_item(name: &str) -> Value {
        json!({
            "name": name,
            "sequence": [
                {"name": "xzmo", "type": "server_game", "exe": "xzmoSvr.exe", "display_name": "d1"},
                {"name": "xzms", "type": "server_room", "exe": "roomsvrxzms.exe", "display_name": "d2"}
            ],
            "created_at": "2025-11-05 14:28:23"
        })
    }

    /// 假启动器: 记录调用顺序; `fail_on` 指定的服务 id 返回 Err。
    struct FakeStart {
        log: std::cell::RefCell<Vec<String>>,
        fail_on: Option<String>,
    }
    impl FakeStart {
        fn new(fail_on: Option<&str>) -> Self {
            Self {
                log: std::cell::RefCell::new(Vec::new()),
                fail_on: fail_on.map(str::to_string),
            }
        }
        fn calls(&self) -> Vec<String> {
            self.log.borrow().clone()
        }
        fn starter(&self) -> impl Fn(&str, &str, &str) -> std::result::Result<String, String> + '_ {
            move |name, t, _exe| {
                let id = format!("{name}_{t}");
                self.log.borrow_mut().push(id.clone());
                if self.fail_on.as_deref() == Some(id.as_str()) {
                    Err(format!("启动服务 {id} 失败"))
                } else {
                    Ok(format!("服务 {id} 启动成功"))
                }
            }
        }
    }

    fn ok_starter() -> impl Fn(&str, &str, &str) -> std::result::Result<String, String> {
        |_: &str, _: &str, _: &str| Ok(String::new())
    }

    // ---- scripts_array ----

    #[test]
    fn test_scripts_array_new_format_passthrough() {
        let s = json!({ "scripts": [seq_item("a")] });
        let got = scripts_array(&s);
        assert_eq!(got.len(), 1);
        assert_eq!(got[0]["name"], "a");
        assert_eq!(got[0]["sequence"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn test_scripts_array_missing_or_invalid_is_empty() {
        assert!(scripts_array(&json!({})).is_empty());
        assert!(scripts_array(&json!({ "scripts": "nonsense" })).is_empty());
        assert!(scripts_array(&json!({ "scripts": 3 })).is_empty());
    }

    #[test]
    fn test_scripts_array_old_dict_converted() {
        let s = json!({
            "scripts": {
                "启动四川麻将": {
                    "start_order": [{ "name": "xzmo", "type": "server_game", "exe": "a.exe" }],
                    "created_at": "2025-11-05 14:28:23"
                }
            }
        });
        let got = scripts_array(&s);
        assert_eq!(got.len(), 1);
        assert_eq!(got[0]["name"], "启动四川麻将");
        assert_eq!(got[0]["sequence"][0]["name"], "xzmo");
        assert_eq!(got[0]["created_at"], "2025-11-05 14:28:23");
    }

    // ---- upsert_sequence ----

    #[test]
    fn test_upsert_appends_new_sequence() {
        let mut s = json!({ "scripts": [] });
        upsert_sequence(&mut s, "n1", &json!([{ "name": "a" }]), "2026-01-01 00:00:00");
        let arr = s["scripts"].as_array().unwrap();
        assert_eq!(arr.len(), 1);
        assert_eq!(arr[0]["name"], "n1");
        assert_eq!(arr[0]["sequence"][0]["name"], "a");
        assert_eq!(arr[0]["created_at"], "2026-01-01 00:00:00");
    }

    #[test]
    fn test_upsert_replaces_same_name_in_place() {
        let mut s = json!({ "scripts": [seq_item("dup"), seq_item("other")] });
        upsert_sequence(&mut s, "dup", &json!([{ "name": "z" }]), "2026-02-02 00:00:00");
        let arr = s["scripts"].as_array().unwrap();
        assert_eq!(arr.len(), 2, "同名应原位替换而非追加");
        assert_eq!(arr[0]["name"], "dup");
        assert_eq!(arr[0]["sequence"][0]["name"], "z");
        assert_eq!(arr[0]["created_at"], "2026-02-02 00:00:00");
        assert_eq!(arr[1]["name"], "other");
    }

    #[test]
    fn test_upsert_resets_old_dict_and_preserves_root_keys() {
        let mut s = json!({
            "start_order": ["xg"],
            "scripts": { "old": { "start_order": [] } }
        });
        upsert_sequence(&mut s, "n", &json!([]), "t");
        assert!(s["scripts"].is_array(), "旧 dict 格式应重置为数组");
        assert_eq!(s["scripts"].as_array().unwrap().len(), 1);
        assert_eq!(s["scripts"][0]["name"], "n");
        assert_eq!(s["start_order"][0], "xg", "根级 start_order 必须保留");
    }

    #[test]
    fn test_upsert_on_missing_scripts_key() {
        let mut s = json!({ "start_order": [] });
        upsert_sequence(&mut s, "n", &json!([{ "name": "a" }]), "t");
        assert_eq!(s["scripts"].as_array().unwrap().len(), 1);
    }

    // ---- run_sequence ----

    #[test]
    fn test_run_sequence_success_all() {
        let script = json!({ "scripts": [seq_item("s")] });
        let config = json!({ "service": {} });
        let fake = FakeStart::new(None);
        let start = fake.starter();

        let (code, body) = run_sequence(&script, &config, "s", Duration::ZERO, &start);

        assert_eq!(code, StatusCode::OK);
        assert_eq!(body["success"], true);
        assert_eq!(body["message"], "所有服务已成功启动");
        assert_eq!(body["results"].as_array().unwrap().len(), 2);
        assert_eq!(body["results"][0]["name"], "xzmo");
        assert_eq!(body["results"][0]["type"], "server_game");
        assert_eq!(body["results"][0]["success"], true);
        assert_eq!(body["results"][0]["message"], "服务 xzmo_server_game 启动成功");
        assert_eq!(
            fake.calls(),
            vec!["xzmo_server_game", "xzms_server_room"],
            "应按序列顺序启动"
        );
    }

    #[test]
    fn test_run_sequence_start_failure_stops_early_and_reports() {
        let script = json!({ "scripts": [seq_item("s")] });
        let config = json!({ "service": {} });
        let fake = FakeStart::new(Some("xzmo_server_game"));
        let start = fake.starter();

        let (code, body) = run_sequence(&script, &config, "s", Duration::ZERO, &start);

        assert_eq!(code, StatusCode::OK, "legacy 对启动中途失败返 200");
        assert_eq!(body["success"], false);
        assert_eq!(body["message"], "服务启动失败: 启动服务 xzmo_server_game 失败");
        assert_eq!(body["failed_at"], 0);
        assert_eq!(body["failed_service"], "xzmo_server_game");
        assert_eq!(body["results"].as_array().unwrap().len(), 1);
        assert_eq!(fake.calls(), vec!["xzmo_server_game"], "失败后不再启动后续服务");
    }

    #[test]
    fn test_run_sequence_unknown_sequence_404() {
        let start = ok_starter();
        let (code, body) = run_sequence(
            &json!({ "scripts": [] }),
            &json!({}),
            "nope",
            Duration::ZERO,
            &start,
        );
        assert_eq!(code, StatusCode::NOT_FOUND);
        assert_eq!(body["success"], false);
        assert_eq!(body["message"], "启动序列 \"nope\" 不存在");
    }

    #[test]
    fn test_run_sequence_missing_sequence_key_404() {
        // 序列存在但无 sequence 数组 (旧格式条目走 start_order 兼容; 都没有则 404)
        let script = json!({ "scripts": [{ "name": "s", "created_at": "t" }] });
        let start = ok_starter();
        let (code, _body) = run_sequence(&script, &json!({}), "s", Duration::ZERO, &start);
        assert_eq!(code, StatusCode::NOT_FOUND);
    }

    #[test]
    fn test_run_sequence_incomplete_entry_400() {
        let script = json!({
            "scripts": [{ "name": "s", "sequence": [{ "name": "xzmo", "type": "", "exe": "a.exe" }] }]
        });
        let start = ok_starter();
        let (code, body) = run_sequence(&script, &json!({}), "s", Duration::ZERO, &start);
        assert_eq!(code, StatusCode::BAD_REQUEST);
        assert_eq!(body["success"], false);
        assert_eq!(body["message"], "序列中第1个服务的参数不完整");
        assert_eq!(body["failed_at"], 0);
    }

    #[test]
    fn test_run_sequence_invalid_entry_type_400() {
        let script = json!({ "scripts": [{ "name": "s", "sequence": [42] }] });
        let start = ok_starter();
        let (code, body) = run_sequence(&script, &json!({}), "s", Duration::ZERO, &start);
        assert_eq!(code, StatusCode::BAD_REQUEST);
        assert_eq!(body["message"], "序列中第1个服务的数据格式无效");
    }

    #[test]
    fn test_run_sequence_group_entry_starts_whole_group() {
        let script = json!({ "scripts": [{ "name": "s", "sequence": ["xg"] }] });
        let config = json!({ "service": { "xg": [
            { "type": "server_game", "exe": "g.exe" },
            { "type": "server_room", "exe": "r.exe" }
        ] } });
        let fake = FakeStart::new(None);
        let start = fake.starter();

        let (code, body) = run_sequence(&script, &config, "s", Duration::ZERO, &start);

        assert_eq!(code, StatusCode::OK);
        assert_eq!(body["success"], true);
        assert_eq!(fake.calls(), vec!["xg_server_game", "xg_server_room"]);
        assert_eq!(body["results"][0]["name"], "xg");
    }

    #[test]
    fn test_run_sequence_group_missing_400() {
        let script = json!({ "scripts": [{ "name": "s", "sequence": ["nope"] }] });
        let start = ok_starter();
        let (code, body) = run_sequence(
            &script,
            &json!({ "service": {} }),
            "s",
            Duration::ZERO,
            &start,
        );
        assert_eq!(code, StatusCode::BAD_REQUEST);
        assert_eq!(body["message"], "服务组 nope 不存在");
        assert_eq!(body["failed_at"], 0);
    }

    #[test]
    fn test_run_sequence_old_dict_script_format_supported() {
        let script = json!({
            "scripts": { "s": { "start_order": [
                { "name": "xzmo", "type": "server_game", "exe": "a.exe" }
            ] } }
        });
        let fake = FakeStart::new(None);
        let start = fake.starter();
        let (code, body) = run_sequence(&script, &json!({}), "s", Duration::ZERO, &start);
        assert_eq!(code, StatusCode::OK);
        assert_eq!(body["success"], true);
        assert_eq!(fake.calls(), vec!["xzmo_server_game"]);
    }

    // ---- 时间 ----

    #[test]
    fn test_format_epoch_utc_known_values() {
        assert_eq!(format_epoch_utc(0), "1970-01-01 00:00:00");
        assert_eq!(format_epoch_utc(946_684_800), "2000-01-01 00:00:00");
        assert_eq!(format_epoch_utc(1_700_000_000), "2023-11-14 22:13:20");
        // 2026-01-01 00:00:00 UTC (非闰年 2025 全年 365 天)
        assert_eq!(format_epoch_utc(1_767_225_600), "2026-01-01 00:00:00");
    }

    #[test]
    fn test_format_local_now_shape() {
        let s = format_local_now();
        assert_eq!(s.len(), 19, "YYYY-MM-DD HH:MM:SS: {s}");
        assert_eq!(&s[4..5], "-");
        assert_eq!(&s[7..8], "-");
        assert_eq!(&s[10..11], " ");
        assert_eq!(&s[13..14], ":");
        assert_eq!(&s[16..17], ":");
        let year: i32 = s[..4].parse().expect("年份应为数字");
        assert!((2015..=2100).contains(&year), "年份应合理, got {year}");
    }
}
