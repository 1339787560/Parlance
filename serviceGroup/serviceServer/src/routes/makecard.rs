//! 做牌器 (`/api/makecard/*`) 与发牌配置 (`/api/makedeal/*`) —— U2 迁移 (2026-09-21)。
//!
//! 迁移自 legacy `CustomRoute/ServiceRoute.py` (做牌器 test.ini 读写 + 做牌接口)。
//!
//! **做牌器**直接在**本机服务目录**读写 `test*.ini`（**不要求游戏服务在跑**）:
//!   - 目录 = `<abspath>/<svc>/server_game`。legacy 把 `D:\game\{svc}\server_game`
//!     硬编码在三元组里；此处改由 config 的 `abspath` 派生（行为等价，且不再写死盘符），
//!     服务白名单仍是 xzmo / xzms / xzmo2。
//!   - 生效文件恒为 `test.ini`（禁删除、禁改名）；场景备份统一落 `remove/` 子目录。
//!   - 读自动探测编码；`save` 恒按 UTF-8 原位写（对齐 legacy）；`activate` 按**原字节**
//!     落位（保留被激活文件的原编码）。
//!   - `Made` 开关走**字节级改写**：只替换/插入 Made 行，其余字节原样 —— 保 GBK 编码
//!     与 CRLF/LF 风格不被破坏（引擎 `GetPrivateProfileInt` 按 ANSI 解析）。
//!
//! **发牌配置**写 `config.json` 的 `makedealFilePath`（默认
//! `D:/game/zgdb/server_assist/makedeal.json`），落 `StartDeal` / `StartDeal_<roomId>` 字段。

use crate::error::Result;
use crate::state::AppState;
use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::Json;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::path::{Component, Path, PathBuf};

/// 做牌器支持的服务（legacy 硬编码三元组，语义上是白名单）。
const MAKECARD_SERVICES: &[&str] = &["xzmo", "xzms", "xzmo2"];
/// 做牌场景所在的服务类型目录（legacy 写死 server_game）。
const MAKECARD_SVC_TYPE: &str = "server_game";
/// 生效文件名（禁删/禁改名）。
const ACTIVE_FILE: &str = "test.ini";
/// 场景备份子目录。
const REMOVE_DIR: &str = "remove";

// ---------- 路径与文件名 ----------

/// 做牌目录 = `<abspath>/<svc>/server_game`；服务不在白名单 -> None。
fn makecard_base(abspath: &str, svc: &str) -> Option<PathBuf> {
    if !MAKECARD_SERVICES.contains(&svc) {
        return None;
    }
    Some(PathBuf::from(abspath).join(svc).join(MAKECARD_SVC_TYPE))
}

/// 取路径末段（对齐 legacy `file.split('/')[-1]`）。
fn basename(file: &str) -> &str {
    file.rsplit('/').next().unwrap_or(file)
}

/// 文件名白名单：`^test[\w.-]*\.ini$`（忽略大小写；`\w` 含 Unicode 字母数字）。
///
/// 手写而非引入 regex：Cargo 无 regex 依赖，且此规则只需一次字符扫描。
pub fn is_makecard_filename(name: &str) -> bool {
    if name.len() < 8 || !name[..4].eq_ignore_ascii_case("test") {
        return false;
    }
    if !name[name.len() - 4..].eq_ignore_ascii_case(".ini") {
        return false;
    }
    name[4..name.len() - 4]
        .chars()
        .all(|c| c.is_alphanumeric() || c == '_' || c == '-' || c == '.')
}

/// 归一化路径分量（去 `.`、解 `..`），与 `path_check::normalize` 同语义。
fn norm_components(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in p.components() {
        match c {
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// `target` 相对 `base` 的 `/` 分隔路径；不在 `base` 之下 -> None（越界）。
pub fn rel_posix(base: &Path, target: &Path) -> Option<String> {
    let rel = norm_components(target)
        .strip_prefix(norm_components(base))
        .ok()?
        .to_path_buf();
    Some(
        rel.components()
            .map(|c| c.as_os_str().to_string_lossy().into_owned())
            .collect::<Vec<_>>()
            .join("/"),
    )
}

/// 解析 `file` 参数为 `base` 下的绝对路径。Err 为 legacy 的同款错误文案。
pub fn resolve_file(
    base: &Path,
    file: &str,
) -> std::result::Result<PathBuf, &'static str> {
    if !is_makecard_filename(basename(file)) {
        return Err("非法文件名（需 test*.ini）");
    }
    let path = base.join(file);
    if !crate::path_check::is_within(&path, base) {
        return Err("路径越界");
    }
    Ok(path)
}

/// Windows 展示形态：统一反斜杠（对齐 legacy 硬编码 `D:\game\...` 的文案口径）。
fn disp(p: &Path) -> String {
    let s = p.display().to_string();
    if cfg!(windows) {
        s.replace('/', "\\")
    } else {
        s
    }
}

/// 列目录下匹配 `test*.ini` 的名字（已排序）；目录不存在 -> 空。
fn sorted_makecard_names(dir: &Path) -> Vec<String> {
    let mut names: Vec<String> = match std::fs::read_dir(dir) {
        Ok(rd) => rd
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| is_makecard_filename(n))
            .collect(),
        Err(_) => Vec::new(),
    };
    names.sort();
    names
}

/// 把 `suffix` 追加到文件名末尾（对齐 legacy `path + '.bak'`，不经 display 往返）。
fn with_suffix(p: &Path, suffix: &str) -> PathBuf {
    let mut os = p.as_os_str().to_os_string();
    os.push(suffix);
    PathBuf::from(os)
}

// ---------- Made 开关（字节级） ----------

/// test.ini 里 `Made` 行的位置与值（`[start, end)` 为整行，不含换行）。
#[derive(Debug, Clone, PartialEq)]
pub struct MadeLine {
    pub value: i64,
    pub start: usize,
    pub end: usize,
}

/// 按行扫描找 `Made` 行（等价 legacy `(?mi)^[ \t]*Made[ \t]*=[^\r\n]*`）。
///
/// 大小写不敏感；行首允空格/制表符；值非整数按引擎缺省 0 处理。
pub fn find_made_line(raw: &[u8]) -> Option<MadeLine> {
    let mut pos = 0usize;
    while pos <= raw.len() {
        let nl = raw[pos..].iter().position(|&b| b == b'\n');
        let mut end = match nl {
            Some(off) => pos + off,
            None => raw.len(),
        };
        let next = if nl.is_some() { end + 1 } else { raw.len() + 1 };
        if end > pos && raw[end - 1] == b'\r' {
            end -= 1;
        }
        if let Some(value) = parse_made_line(&raw[pos..end]) {
            return Some(MadeLine { value, start: pos, end });
        }
        if nl.is_none() {
            break;
        }
        pos = next;
    }
    None
}

/// 解析单行是否为 `Made = <int>`；不是则 None（值非法时按 0 返回）。
fn parse_made_line(line: &[u8]) -> Option<i64> {
    let text = std::str::from_utf8(line).ok()?;
    let t = text.trim_start_matches([' ', '\t']);
    let rest = t.get(..4)?;
    if !rest.eq_ignore_ascii_case("made") {
        return None;
    }
    let after = t[4..].trim_start_matches([' ', '\t']);
    let value = after.strip_prefix('=')?;
    Some(value.trim().parse::<i64>().unwrap_or(0))
}

/// 读生效 test.ini 的 Made 值（无键/非法值 = 0，与引擎缺省一致）。
pub fn read_made(path: &Path) -> std::result::Result<i64, String> {
    let raw = std::fs::read(path).map_err(|e| e.to_string())?;
    Ok(find_made_line(&raw).map(|m| m.value).unwrap_or(0))
}

/// 字节级改写 Made：有行则原位替换（首个），无行则插到 `[Card]` 节后，
/// 连 `[Card]` 都没有则插到文件头。其余字节一律原样。
pub fn rewrite_made(raw: &[u8], made: i64) -> Vec<u8> {
    let new_line = format!("Made={made}").into_bytes();
    if let Some(m) = find_made_line(raw) {
        let mut out = Vec::with_capacity(raw.len());
        out.extend_from_slice(&raw[..m.start]);
        out.extend_from_slice(&new_line);
        out.extend_from_slice(&raw[m.end..]);
        return out;
    }
    // 无 Made 行 -> 找 [Card] 节行，插到该行之后（跟随其换行风格）
    if let Some((sec_end, nl)) = find_card_section(raw) {
        let mut out = Vec::with_capacity(raw.len() + new_line.len() + nl.len());
        out.extend_from_slice(&raw[..sec_end]);
        out.extend_from_slice(nl);
        out.extend_from_slice(&new_line);
        out.extend_from_slice(&raw[sec_end..]);
        return out;
    }
    // 连 [Card] 都没有 -> 文件头插入
    let mut out = Vec::with_capacity(raw.len() + new_line.len() + 2);
    out.extend_from_slice(&new_line);
    out.extend_from_slice(b"\r\n");
    out.extend_from_slice(raw);
    out
}

/// 找 `^[ \t]*\[Card\]` 行：返回（行文本结束偏移, 该行换行符）。
fn find_card_section(raw: &[u8]) -> Option<(usize, &'static [u8])> {
    let mut pos = 0usize;
    while pos < raw.len() {
        let nl = raw[pos..].iter().position(|&b| b == b'\n');
        let mut end = match nl {
            Some(off) => pos + off,
            None => raw.len(),
        };
        if end > pos && raw[end - 1] == b'\r' {
            end -= 1;
        }
        if let Ok(text) = std::str::from_utf8(&raw[pos..end]) {
            let t = text.trim_start_matches([' ', '\t']);
            if t.len() >= 6 && t[..6].eq_ignore_ascii_case("[card]") {
                let nl_bytes: &'static [u8] = if raw[end..].starts_with(b"\r\n") {
                    b"\r\n"
                } else {
                    b"\n"
                };
                return Some((end, nl_bytes));
            }
        }
        match nl {
            Some(off) => pos += off + 1,
            None => break,
        }
    }
    None
}

// ---------- 发牌配置（makedeal.json） ----------

/// 牌号字段清单（必填 + 顺序即报错顺序）。
const CARD_FIELDS: [&str; 5] = ["Chair0", "Chair1", "Chair2", "Bottom", "Total"];

/// 校验请求体并构建 (字段名, 写入数据)。纯函数，便于单测。
///
/// Err = (HTTP 码, 文案)，与 legacy 逐条校验同序同文案。
pub fn build_makedeal_write(body: &Value) -> std::result::Result<(String, Value), (u16, String)> {
    let obj = body
        .as_object()
        .ok_or((400u16, "请求体不是合法 JSON".to_string()))?;
    for field in CARD_FIELDS {
        if !obj.contains_key(field) {
            return Err((400, format!("缺少必填字段: {field}")));
        }
    }

    let mut parsed: Vec<(String, Vec<i64>)> = Vec::new();
    for field in CARD_FIELDS {
        let value = obj.get(field).and_then(Value::as_str).unwrap_or("");
        if value.is_empty() {
            return Err((400, format!("{field} 必须是非空字符串")));
        }
        let mut cards: Vec<i64> = Vec::new();
        for part in value.split('|') {
            let n: i64 = part
                .parse()
                .map_err(|_| (400u16, format!("{field} 中包含非整数: {part}")))?;
            if !(0..=53).contains(&n) {
                return Err((400, format!("{field} 中牌号超出范围(0-53): {n}")));
            }
            cards.push(n);
        }
        let uniq: BTreeSet<i64> = cards.iter().copied().collect();
        if uniq.len() != cards.len() {
            return Err((400, format!("{field} 中存在重复牌号")));
        }
        parsed.push((field.to_string(), cards));
    }

    // Chair0/1/2/Bottom 互不重叠
    let mut combined: Vec<i64> = Vec::new();
    for (field, cards) in &parsed {
        if *field != "Total" {
            combined.extend_from_slice(cards);
        }
    }
    let combined_set: BTreeSet<i64> = combined.iter().copied().collect();
    if combined_set.len() != combined.len() {
        return Err((400, "Chair0/Chair1/Chair2/Bottom 之间存在重复牌号".to_string()));
    }
    // Total 与四家集合一致（不要求顺序）
    let total: &Vec<i64> = &parsed
        .iter()
        .find(|(f, _)| f == "Total")
        .map(|(_, c)| c)
        .expect("Total 已校验存在");
    let total_set: BTreeSet<i64> = total.iter().copied().collect();
    if total_set != combined_set {
        return Err((
            400,
            "Total 的牌号集合与 Chair0+Chair1+Chair2+Bottom 不一致".to_string(),
        ));
    }
    if total.len() != combined.len() {
        return Err((
            400,
            "Total 的牌号数量与 Chair0+Chair1+Chair2+Bottom 不一致".to_string(),
        ));
    }

    let mut write = json!({
        "ReadCardsFromFile": 1,
        "Chair0": obj.get("Chair0").cloned().unwrap_or(Value::Null),
        "Chair1": obj.get("Chair1").cloned().unwrap_or(Value::Null),
        "Chair2": obj.get("Chair2").cloned().unwrap_or(Value::Null),
        "Bottom": obj.get("Bottom").cloned().unwrap_or(Value::Null),
        "Total": obj.get("Total").cloned().unwrap_or(Value::Null),
    });
    // 可选字段：类型不符即报错（文案逐条对齐 legacy）
    for (key, target) in [
        ("RazzValue", "RazzValue"),
        ("Banker", "Banker"),
        ("randomReject", "RandomReject"),
    ] {
        if let Some(v) = obj.get(key) {
            let n = v
                .as_i64()
                .ok_or((400u16, format!("{key} 必须是整数")))?;
            write[target] = json!(n);
        }
    }

    let field_name = match obj.get("roomId") {
        Some(v) => {
            let room = v
                .as_i64()
                .ok_or((400u16, "roomId 必须是整数".to_string()))?;
            if room <= 0 {
                return Err((400, "roomId 必须是正整数".to_string()));
            }
            format!("StartDeal_{room}")
        }
        None => "StartDeal".to_string(),
    };
    Ok((field_name, write))
}

/// `randomReject` 单独更新：字段不存在/非对象时按 legacy 默认骨架新建，只改值。
pub fn upsert_random_reject(existing: &mut Value, room_id: i64, value: i64) {
    if !existing.is_object() {
        *existing = json!({});
    }
    let obj = existing.as_object_mut().expect("root 已归一为对象");
    let key = format!("StartDeal_{room_id}");
    let need_new = obj
        .get(&key)
        .map(|v| !v.is_object())
        .unwrap_or(true);
    if need_new {
        obj.insert(
            key.clone(),
            json!({
                "ReadCardsFromFile": 0,
                "Chair0": "",
                "Chair1": "",
                "Chair2": "",
                "Bottom": "",
                "Total": "",
            }),
        );
    }
    obj.get_mut(&key)
        .and_then(Value::as_object_mut)
        .expect("骨架已建为对象")
        .insert("RandomReject".to_string(), json!(value));
}

/// 读 config.json 的 `makedealFilePath`；未配置 -> Err(文案)。
fn makedeal_path(state: &AppState) -> std::result::Result<PathBuf, (u16, String)> {
    let config = crate::routes::read_config_value(&state.config_path)
        .map_err(|e| (500u16, e.to_string()))?;
    let raw = config
        .get("makedealFilePath")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or((400u16, "config.json 中未配置 makedealFilePath".to_string()))?;
    Ok(PathBuf::from(raw))
}

/// 读 makedeal.json 为 JSON 对象；缺文件 -> `{}`；解析/读取失败 -> Err(文案)。
fn read_makedeal(path: &Path) -> std::result::Result<Value, String> {
    match std::fs::read_to_string(path) {
        Ok(raw) => serde_json::from_str(&raw)
            .map_err(|e| format!("读取 makedeal.json 失败: {e}")),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(json!({})),
        Err(e) => Err(format!("读取 makedeal.json 失败: {e}")),
    }
}

/// 写 JSON：4 空格缩进 + 建父目录 + 原位写（对齐 legacy `json.dump(indent=4)` + `open('w')`）。
fn write_json_pretty(path: &Path, value: &Value) -> std::result::Result<(), String> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let mut buf = Vec::new();
    let fmt = serde_json::ser::PrettyFormatter::with_indent(b"    ");
    let mut ser = serde_json::Serializer::with_formatter(&mut buf, fmt);
    value.serialize(&mut ser).map_err(|e| e.to_string())?;
    crate::atomic_write::write_in_place_bytes(path, &buf).map_err(|e| e.to_string())
}

// ---------- 响应助手 ----------

fn ok_json(body: Value) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, Json(body))
}

fn bad_request(msg: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::BAD_REQUEST,
        Json(json!({ "success": false, "message": msg })),
    )
}

fn not_found(msg: String) -> (StatusCode, Json<Value>) {
    (
        StatusCode::NOT_FOUND,
        Json(json!({ "success": false, "message": msg })),
    )
}

fn err500(msg: String) -> (StatusCode, Json<Value>) {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(json!({ "success": false, "message": msg })),
    )
}

/// legacy `data.get('service')` 取不到时 f-string 出 "None"，保持一致。
fn svc_of(body: &Value) -> String {
    body.get("service")
        .and_then(Value::as_str)
        .unwrap_or("None")
        .to_string()
}

fn str_field<'a>(body: &'a Value, key: &str) -> &'a str {
    body.get(key).and_then(Value::as_str).unwrap_or("")
}

// ---------- handlers: 做牌器 ----------

#[derive(Deserialize)]
pub struct FilesQuery {
    pub service: Option<String>,
}

/// GET /api/makecard/files — 列 `test*.ini`（含 `remove/` 备份，根目录在前）。
pub async fn files(
    State(state): State<AppState>,
    Query(q): Query<FilesQuery>,
) -> Result<(StatusCode, Json<Value>)> {
    state.path_map.refresh(&state.config_path)?;
    let svc = q.service.unwrap_or_else(|| "None".to_string());
    let Some(base) = makecard_base(&state.path_map.abspath(), &svc) else {
        return Ok(bad_request(&format!("不支持的服务: {svc}")));
    };
    let mut out = sorted_makecard_names(&base);
    let remove_dir = base.join(REMOVE_DIR);
    for name in sorted_makecard_names(&remove_dir) {
        out.push(format!("{REMOVE_DIR}/{name}"));
    }
    Ok(ok_json(json!({
        "success": true,
        "files": out,
        "service": svc,
        "base": disp(&base),
    })))
}

#[derive(Deserialize)]
pub struct ReadQuery {
    pub service: Option<String>,
    pub file: Option<String>,
}

/// GET /api/makecard/read — 读 test*.ini 内容（自动探测编码）。
pub async fn read(
    State(state): State<AppState>,
    Query(q): Query<ReadQuery>,
) -> Result<(StatusCode, Json<Value>)> {
    state.path_map.refresh(&state.config_path)?;
    let svc = q.service.unwrap_or_else(|| "None".to_string());
    let file = q.file.unwrap_or_default();
    let Some(base) = makecard_base(&state.path_map.abspath(), &svc) else {
        return Ok(bad_request(&format!("不支持的服务: {svc}")));
    };
    let path = match resolve_file(&base, &file) {
        Ok(p) => p,
        Err(msg) => return Ok(bad_request(msg)),
    };
    if !path.exists() {
        return Ok(not_found(format!("文件不存在: {file}")));
    }
    match std::fs::read(&path) {
        Ok(raw) => {
            let decoded = crate::encoding::decode(&raw);
            Ok(ok_json(json!({
                "success": true,
                "content": decoded.content,
                "file": file,
                "service": svc,
            })))
        }
        Err(e) => Ok(err500(e.to_string())),
    }
}

/// POST /api/makecard/save — 保存做牌内容（首次写前 `.bak` 备份，UTF-8 原位写）。
pub async fn save(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    state.path_map.refresh(&state.config_path)?;
    let svc = svc_of(&body);
    let file = str_field(&body, "file").to_string();
    let Some(base) = makecard_base(&state.path_map.abspath(), &svc) else {
        return Ok(bad_request(&format!("不支持的服务: {svc}")));
    };
    if !is_makecard_filename(basename(&file)) {
        return Ok(bad_request("非法文件名（需 test*.ini）"));
    }
    let Some(content) = body.get("content").and_then(Value::as_str) else {
        return Ok(bad_request("缺少 content"));
    };
    let path = match resolve_file(&base, &file) {
        Ok(p) => p,
        Err(msg) => return Ok(bad_request(msg)),
    };
    // 写前备份：同目录 `<file>.bak`，不覆盖已存在的备份（对齐 legacy shutil.copy2 + 失败忽略）
    if path.exists() {
        let bak = with_suffix(&path, ".bak");
        if !bak.exists() {
            let _ = std::fs::copy(&path, &bak);
        }
    }
    match crate::atomic_write::write_in_place_bytes(&path, content.as_bytes()) {
        Ok(()) => Ok(ok_json(json!({
            "success": true,
            "message": "已保存",
            "file": file,
            "service": svc,
            "path": disp(&path),
        }))),
        Err(e) => Ok(err500(e.to_string())),
    }
}

/// POST /api/makecard/activate — 把指定 test*.ini 设为生效（旧 test.ini 先备份到 `remove/`）。
pub async fn activate(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    state.path_map.refresh(&state.config_path)?;
    let svc = svc_of(&body);
    let file = str_field(&body, "file").to_string();
    let Some(base) = makecard_base(&state.path_map.abspath(), &svc) else {
        return Ok(bad_request(&format!("不支持的服务: {svc}")));
    };
    if !is_makecard_filename(basename(&file)) {
        return Ok(bad_request("非法文件名（需 test*.ini）"));
    }
    if file == ACTIVE_FILE {
        return Ok(bad_request("test.ini 已是生效文件"));
    }
    let src = match resolve_file(&base, &file) {
        Ok(p) => p,
        Err(msg) => return Ok(bad_request(msg)),
    };
    if !src.exists() {
        return Ok(not_found(format!("文件不存在: {file}")));
    }
    let raw = match std::fs::read(&src) {
        Ok(b) => b,
        Err(e) => return Ok(err500(e.to_string())),
    };
    let content = crate::encoding::decode(&raw).content;
    let active = base.join(ACTIVE_FILE);
    // 备份当前生效文件（时间戳命名，不覆盖）
    let mut backup_rel = String::new();
    if active.exists() {
        let remove_dir = base.join(REMOVE_DIR);
        if let Err(e) = std::fs::create_dir_all(&remove_dir) {
            return Ok(err500(e.to_string()));
        }
        backup_rel = format!("{REMOVE_DIR}/{ACTIVE_FILE}.bak.{}", crate::localtime::now_stamp());
        if let Err(e) = std::fs::copy(&active, base.join(&backup_rel)) {
            return Ok(err500(e.to_string()));
        }
    }
    // 目标按原字节落位（保留被激活文件的原编码）
    if let Err(e) = crate::atomic_write::write_in_place_bytes(&active, &raw) {
        return Ok(err500(e.to_string()));
    }
    let shown = if backup_rel.is_empty() {
        "无（原 test.ini 不存在）".to_string()
    } else {
        backup_rel.clone()
    };
    Ok(ok_json(json!({
        "success": true,
        "message": format!("已生效（旧 test.ini → {shown}）"),
        "backup": backup_rel,
        "content": content,
        "activated": file,
        "service": svc,
    })))
}

/// POST /api/makecard/delete — 删除场景文件（生效 test.ini 禁删）。
pub async fn delete(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    state.path_map.refresh(&state.config_path)?;
    let svc = svc_of(&body);
    let file = str_field(&body, "file").to_string();
    let Some(base) = makecard_base(&state.path_map.abspath(), &svc) else {
        return Ok(bad_request(&format!("不支持的服务: {svc}")));
    };
    let path = match resolve_file(&base, &file) {
        Ok(p) => p,
        Err(msg) => return Ok(bad_request(msg)),
    };
    if rel_posix(&base, &path)
        .map(|r| r.eq_ignore_ascii_case(ACTIVE_FILE))
        .unwrap_or(false)
    {
        return Ok(bad_request("test.ini 为生效文件，禁止删除"));
    }
    if !path.exists() {
        return Ok(not_found(format!("文件不存在: {file}")));
    }
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(ok_json(json!({
            "success": true,
            "message": format!("已删除 {file}"),
            "file": file,
            "service": svc,
        }))),
        Err(e) => Ok(err500(e.to_string())),
    }
}

/// POST /api/makecard/rename — 场景改名（生效 test.ini 禁改；新名不含路径，落根目录）。
pub async fn rename(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    state.path_map.refresh(&state.config_path)?;
    let svc = svc_of(&body);
    let file = str_field(&body, "file").to_string();
    let new_file = str_field(&body, "newFile").to_string();
    let Some(base) = makecard_base(&state.path_map.abspath(), &svc) else {
        return Ok(bad_request(&format!("不支持的服务: {svc}")));
    };
    if !is_makecard_filename(basename(&file)) {
        return Ok(bad_request("非法文件名（需 test*.ini）"));
    }
    if new_file.is_empty() || new_file.contains('/') || !is_makecard_filename(&new_file) {
        return Ok(bad_request("非法新文件名（需 test*.ini，不含路径）"));
    }
    let src = match resolve_file(&base, &file) {
        Ok(p) => p,
        Err(msg) => return Ok(bad_request(msg)),
    };
    if rel_posix(&base, &src)
        .map(|r| r.eq_ignore_ascii_case(ACTIVE_FILE))
        .unwrap_or(false)
    {
        return Ok(bad_request("test.ini 为生效文件，禁止重命名"));
    }
    let dst = base.join(&new_file);
    if !src.exists() {
        return Ok(not_found(format!("文件不存在: {file}")));
    }
    if dst.exists() {
        return Ok(bad_request(&format!("目标已存在: {new_file}")));
    }
    if src.to_string_lossy().eq_ignore_ascii_case(&dst.to_string_lossy()) {
        return Ok(bad_request("新文件名与原名相同"));
    }
    match std::fs::rename(&src, &dst) {
        Ok(()) => Ok(ok_json(json!({
            "success": true,
            "message": format!("已重命名 {file} → {new_file}"),
            "file": new_file,
            "service": svc,
        }))),
        Err(e) => Ok(err500(e.to_string())),
    }
}

/// GET /api/makecard/made — 查生效 test.ini 的做牌开关。
pub async fn made(
    State(state): State<AppState>,
    Query(q): Query<FilesQuery>,
) -> Result<(StatusCode, Json<Value>)> {
    state.path_map.refresh(&state.config_path)?;
    let svc = q.service.unwrap_or_else(|| "None".to_string());
    let Some(base) = makecard_base(&state.path_map.abspath(), &svc) else {
        return Ok(bad_request(&format!("不支持的服务: {svc}")));
    };
    let path = base.join(ACTIVE_FILE);
    if !path.exists() {
        return Ok(not_found(format!(
            "生效文件不存在: test.ini（{}）",
            disp(&base)
        )));
    }
    match read_made(&path) {
        Ok(m) => Ok(ok_json(json!({ "success": true, "service": svc, "made": m }))),
        Err(e) => Ok(err500(e)),
    }
}

/// POST /api/makecard/toggle — 开关做牌（`[Card] Made`，1=开 0=关）。
///
/// 关闭（1→0）前整份备份 test.ini → `remove/test_made_on.<ts>.ini`：关闭态引擎会把
/// 每局实况随机牌写回 Total，覆盖原布局，留档才能恢复。
pub async fn toggle(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    state.path_map.refresh(&state.config_path)?;
    let svc = svc_of(&body);
    let Some(base) = makecard_base(&state.path_map.abspath(), &svc) else {
        return Ok(bad_request(&format!("不支持的服务: {svc}")));
    };
    let Some(made) = body.get("made").and_then(Value::as_i64) else {
        return Ok(bad_request("made 仅支持 0（关）/ 1（开）"));
    };
    if made != 0 && made != 1 {
        return Ok(bad_request("made 仅支持 0（关）/ 1（开）"));
    }
    let path = base.join(ACTIVE_FILE);
    if !path.exists() {
        return Ok(not_found(format!(
            "生效文件不存在: test.ini（{}）",
            disp(&base)
        )));
    }
    let raw = match std::fs::read(&path) {
        Ok(b) => b,
        Err(e) => return Ok(err500(e.to_string())),
    };
    let cur = find_made_line(&raw).map(|m| m.value).unwrap_or(0);
    if cur == made {
        return Ok(ok_json(json!({
            "success": true,
            "message": format!("已是目标状态（Made={made}），未改动"),
            "service": svc,
            "made": made,
            "backup": Value::Null,
        })));
    }
    let mut backup = Value::Null;
    if made == 0 && cur > 0 {
        let remove_dir = base.join(REMOVE_DIR);
        if let Err(e) = std::fs::create_dir_all(&remove_dir) {
            return Ok(err500(e.to_string()));
        }
        let rel = format!("{REMOVE_DIR}/test_made_on.{}.ini", crate::localtime::now_stamp());
        if let Err(e) = std::fs::copy(&path, base.join(&rel)) {
            return Ok(err500(e.to_string()));
        }
        backup = json!(rel);
    }
    let new_raw = rewrite_made(&raw, made);
    if let Err(e) = crate::atomic_write::write_in_place_bytes(&path, &new_raw) {
        return Ok(err500(e.to_string()));
    }
    let msg = if made == 0 {
        format!("做牌已关闭（Made=0），原布局备份 {backup}")
    } else {
        "做牌已开启（Made=1）".to_string()
    };
    Ok(ok_json(json!({
        "success": true,
        "message": msg,
        "service": svc,
        "made": made,
        "backup": backup,
    })))
}

// ---------- handlers: 发牌配置 ----------

/// POST /api/makedeal/start — 写发牌配置到 makedeal.json 的 StartDeal[_<roomId>]。
pub async fn makedeal_start(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>)> {
    let (field, write_data) = match build_makedeal_write(&body) {
        Ok(v) => v,
        Err((code, msg)) => {
            return Ok((StatusCode::from_u16(code).unwrap_or(StatusCode::BAD_REQUEST), Json(json!({ "success": false, "message": msg }))));
        }
    };
    let path = match makedeal_path(&state) {
        Ok(p) => p,
        Err((code, msg)) => {
            return Ok((StatusCode::from_u16(code).unwrap_or(StatusCode::BAD_REQUEST), Json(json!({ "success": false, "message": msg }))));
        }
    };
    let mut data = match read_makedeal(&path) {
        Ok(v) => v,
        Err(e) => return Ok(err500(e)),
    };
    if !data.is_object() {
        data = json!({});
    }
    data[&field] = write_data;
    match write_json_pretty(&path, &data) {
        Ok(()) => Ok(ok_json(json!({ "success": true, "message": "发牌配置写入成功" }))),
        Err(e) => Ok(err500(e)),
    }
}

#[derive(Deserialize)]
pub struct RandomRejectQuery {
    #[serde(rename = "roomId")]
    pub room_id: Option<String>,
    pub value: Option<String>,
}

/// GET /api/makedeal/randomReject — 单独改 `StartDeal_<roomId>.RandomReject`。
pub async fn makedeal_random_reject(
    State(state): State<AppState>,
    Query(q): Query<RandomRejectQuery>,
) -> Result<(StatusCode, Json<Value>)> {
    let room_raw = match q.room_id {
        Some(v) => v,
        None => return Ok(bad_request("缺少必填参数: roomId")),
    };
    let value_raw = match q.value {
        Some(v) => v,
        None => return Ok(bad_request("缺少必填参数: value")),
    };
    let room_id: i64 = match room_raw.parse() {
        Ok(v) => v,
        Err(_) => return Ok(bad_request("roomId 必须是整数")),
    };
    if room_id <= 0 {
        return Ok(bad_request("roomId 必须是正整数"));
    }
    let value: i64 = match value_raw.parse() {
        Ok(v) => v,
        Err(_) => return Ok(bad_request("value 必须是整数")),
    };
    let path = match makedeal_path(&state) {
        Ok(p) => p,
        Err((code, msg)) => {
            return Ok((StatusCode::from_u16(code).unwrap_or(StatusCode::BAD_REQUEST), Json(json!({ "success": false, "message": msg }))));
        }
    };
    let mut data = match read_makedeal(&path) {
        Ok(v) => v,
        Err(e) => return Ok(err500(e)),
    };
    upsert_random_reject(&mut data, room_id, value);
    match write_json_pretty(&path, &data) {
        Ok(()) => Ok(ok_json(json!({ "success": true, "message": "RandomReject 更新成功" }))),
        Err(e) => Ok(err500(e)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::json;

    // ---- 文件名白名单 ----

    #[rstest]
    #[case::active("test.ini", true)]
    #[case::scenario("test_xyz.ini", true)]
    #[case::dash_dot("test-a.b.ini", true)]
    #[case::upper("TEST.INI", true)]
    #[case::made_backup("test_made_on.20260921_120000.ini", true)]
    #[case::bak_not_ini("test.ini.bak", false)]
    #[case::other("other.ini", false)]
    #[case::no_ext("test", false)]
    #[case::slash_is_not_matched("test/x.ini", false)]
    #[case::ini_only(".ini", false)]
    fn test_is_makecard_filename(#[case] name: &str, #[case] expected: bool) {
        assert_eq!(is_makecard_filename(name), expected);
    }

    // ---- 路径解析 ----

    #[test]
    fn test_rel_posix_inside_and_escape() {
        let base = Path::new("D:/game/xzmo/server_game");
        assert_eq!(
            rel_posix(base, &base.join("test_a.ini")).as_deref(),
            Some("test_a.ini")
        );
        assert_eq!(
            rel_posix(base, &base.join("remove/test.ini.bak.1")).as_deref(),
            Some("remove/test.ini.bak.1")
        );
        // 越界 -> None
        assert!(rel_posix(base, Path::new("D:/game/xzms/server_game/test.ini")).is_none());
    }

    #[rstest]
    #[case::ok("test_a.ini", true)]
    #[case::remove_ok("remove/test_a.ini", true)]
    #[case::escape_dotdot("../test_a.ini", false)]
    #[case::escape_nested("remove/../../test_a.ini", false)]
    #[case::bad_name("evil.ini", false)]
    fn test_resolve_file_containment(#[case] file: &str, #[case] ok: bool) {
        let base = Path::new("D:/game/xzmo/server_game");
        assert_eq!(resolve_file(base, file).is_ok(), ok, "file={file}");
    }

    /// 越界与非法名给出不同文案（legacy 两处分别报错）。
    #[test]
    fn test_resolve_file_error_messages() {
        let base = Path::new("D:/game/xzmo/server_game");
        assert_eq!(
            resolve_file(base, "evil.ini").unwrap_err(),
            "非法文件名（需 test*.ini）"
        );
        assert_eq!(
            resolve_file(base, "../test_a.ini").unwrap_err(),
            "路径越界"
        );
    }

    // ---- Made 字节级开关 ----

    #[test]
    fn test_find_made_line_crlf() {
        let raw = b"[Card]\r\nMade=1\r\nTotal=1|2\r\n";
        let m = find_made_line(raw).unwrap();
        assert_eq!(m.value, 1);
        assert_eq!(&raw[m.start..m.end], b"Made=1");
    }

    #[test]
    fn test_find_made_line_lf_and_case_insensitive() {
        let raw = b"[Card]\n  made = 0 \n";
        let m = find_made_line(raw).unwrap();
        assert_eq!(m.value, 0);
        assert_eq!(&raw[m.start..m.end], b"  made = 0 ");
    }

    #[test]
    fn test_find_made_line_absent_or_invalid() {
        assert!(find_made_line(b"[Card]\r\nTotal=1\r\n").is_none());
        // 非法值按引擎缺省 0
        assert_eq!(find_made_line(b"Made=abc\n").unwrap().value, 0);
    }

    #[test]
    fn test_rewrite_made_replaces_only_that_line() {
        let raw = b"[Card]\r\nMade=1\r\nTotal=1|2\r\n";
        let out = rewrite_made(raw, 0);
        assert_eq!(out, b"[Card]\r\nMade=0\r\nTotal=1|2\r\n".to_vec());
    }

    #[test]
    fn test_rewrite_made_inserts_after_card_section_crlf() {
        let raw = b"[Card]\r\nTotal=1\r\n";
        let out = rewrite_made(raw, 1);
        assert_eq!(out, b"[Card]\r\nMade=1\r\nTotal=1\r\n".to_vec());
    }

    #[test]
    fn test_rewrite_made_inserts_after_card_section_lf() {
        let raw = b"[Card]\nTotal=1\n";
        let out = rewrite_made(raw, 1);
        assert_eq!(out, b"[Card]\nMade=1\nTotal=1\n".to_vec());
    }

    #[test]
    fn test_rewrite_made_head_insert_when_no_card_section() {
        let raw = b"Total=1\r\n";
        let out = rewrite_made(raw, 1);
        assert_eq!(out, b"Made=1\r\nTotal=1\r\n".to_vec());
    }

    /// GBK 字节 + 原换行风格必须原样保留（只动 Made 行）。
    #[test]
    fn test_rewrite_made_preserves_gbk_bytes_and_crlf() {
        // [Card] 段后一行 GBK 中文注释 (0xD6 0xD0 = 中文)
        let mut raw = Vec::new();
        raw.extend_from_slice(b"[Card]\r\nMade=1\r\n");
        raw.extend_from_slice(&[0xD6, 0xD0]);
        raw.extend_from_slice(b"=x\r\n");
        let out = rewrite_made(&raw, 0);
        let mut expected = Vec::new();
        expected.extend_from_slice(b"[Card]\r\nMade=0\r\n");
        expected.extend_from_slice(&[0xD6, 0xD0]);
        expected.extend_from_slice(b"=x\r\n");
        assert_eq!(out, expected);
    }

    #[test]
    fn test_read_made_roundtrip_with_rewrite() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("test.ini");
        std::fs::write(&p, b"[Card]\r\nTotal=1|2\r\n").unwrap();
        assert_eq!(read_made(&p).unwrap(), 0, "无 Made 键 -> 0");
        std::fs::write(&p, rewrite_made(&std::fs::read(&p).unwrap(), 1)).unwrap();
        assert_eq!(read_made(&p).unwrap(), 1);
        std::fs::write(&p, rewrite_made(&std::fs::read(&p).unwrap(), 0)).unwrap();
        assert_eq!(read_made(&p).unwrap(), 0);
    }

    // ---- 发牌配置校验 ----

    fn valid_body() -> Value {
        json!({
            "Chair0": "0|1",
            "Chair1": "2|3",
            "Chair2": "4|5",
            "Bottom": "6",
            "Total": "0|1|2|3|4|5|6",
        })
    }

    #[test]
    fn test_build_makedeal_write_happy_without_room() {
        let (field, data) = build_makedeal_write(&valid_body()).unwrap();
        assert_eq!(field, "StartDeal");
        assert_eq!(data["ReadCardsFromFile"], 1);
        assert_eq!(data["Chair0"], "0|1");
        assert_eq!(data["Total"], "0|1|2|3|4|5|6");
        assert!(data.get("RandomReject").is_none(), "未提供则不写入");
    }

    #[test]
    fn test_build_makedeal_write_with_room_and_optionals() {
        let mut body = valid_body();
        body["roomId"] = json!(7);
        body["RazzValue"] = json!(3);
        body["Banker"] = json!(1);
        body["randomReject"] = json!(5);
        let (field, data) = build_makedeal_write(&body).unwrap();
        assert_eq!(field, "StartDeal_7");
        assert_eq!(data["RazzValue"], 3);
        assert_eq!(data["Banker"], 1);
        assert_eq!(data["RandomReject"], 5, "randomReject -> RandomReject");
    }

    #[rstest]
    #[case::missing_field(json!({"Chair0":"0","Chair1":"1","Chair2":"2","Bottom":"3"}), "缺少必填字段: Total")]
    #[case::empty_field(json!({"Chair0":"","Chair1":"1","Chair2":"2","Bottom":"3","Total":"1|2|3"}), "Chair0 必须是非空字符串")]
    #[case::not_int(json!({"Chair0":"x","Chair1":"1","Chair2":"2","Bottom":"3","Total":"1|2|3"}), "Chair0 中包含非整数: x")]
    #[case::out_of_range(json!({"Chair0":"54","Chair1":"1","Chair2":"2","Bottom":"3","Total":"1|2|3|54"}), "Chair0 中牌号超出范围(0-53): 54")]
    #[case::dup_in_field(json!({"Chair0":"0|0","Chair1":"1","Chair2":"2","Bottom":"3","Total":"0|1|2|3"}), "Chair0 中存在重复牌号")]
    #[case::dup_across(json!({"Chair0":"0","Chair1":"0","Chair2":"2","Bottom":"3","Total":"0|2|3"}), "Chair0/Chair1/Chair2/Bottom 之间存在重复牌号")]
    #[case::total_mismatch(json!({"Chair0":"0","Chair1":"1","Chair2":"2","Bottom":"3","Total":"0|1|2|9"}), "Total 的牌号集合与 Chair0+Chair1+Chair2+Bottom 不一致")]
    #[case::bad_room(json!({"Chair0":"0","Chair1":"1","Chair2":"2","Bottom":"3","Total":"0|1|2|3","roomId":"x"}), "roomId 必须是整数")]
    #[case::bad_room_zero(json!({"Chair0":"0","Chair1":"1","Chair2":"2","Bottom":"3","Total":"0|1|2|3","roomId":0}), "roomId 必须是正整数")]
    #[case::bad_razz(json!({"Chair0":"0","Chair1":"1","Chair2":"2","Bottom":"3","Total":"0|1|2|3","RazzValue":"x"}), "RazzValue 必须是整数")]
    fn test_build_makedeal_write_errors(#[case] body: Value, #[case] expected: &str) {
        let (code, msg) = build_makedeal_write(&body).unwrap_err();
        assert_eq!(code, 400);
        assert_eq!(msg, expected);
    }

    #[test]
    fn test_build_makedeal_write_rejects_non_object() {
        let (code, msg) = build_makedeal_write(&json!(null)).unwrap_err();
        assert_eq!(code, 400);
        assert_eq!(msg, "请求体不是合法 JSON");
    }

    // ---- RandomReject 单独更新 ----

    #[test]
    fn test_upsert_random_reject_creates_default_skeleton() {
        let mut data = json!({});
        upsert_random_reject(&mut data, 9, 4);
        let d = &data["StartDeal_9"];
        assert_eq!(d["ReadCardsFromFile"], 0);
        assert_eq!(d["Chair0"], "");
        assert_eq!(d["RandomReject"], 4);
    }

    #[test]
    fn test_upsert_random_reject_preserves_existing_fields() {
        let mut data = json!({
            "StartDeal_9": {"ReadCardsFromFile": 1, "Chair0": "0|1", "Total": "0|1"},
            "StartDeal_1": {"RandomReject": 2},
        });
        upsert_random_reject(&mut data, 9, 7);
        assert_eq!(data["StartDeal_9"]["RandomReject"], 7);
        assert_eq!(data["StartDeal_9"]["Chair0"], "0|1", "其它字段不动");
        assert_eq!(data["StartDeal_9"]["ReadCardsFromFile"], 1);
        assert_eq!(data["StartDeal_1"]["RandomReject"], 2, "别的房间不受影响");
    }

    #[test]
    fn test_upsert_random_reject_replaces_non_object_field() {
        let mut data = json!({ "StartDeal_3": "broken" });
        upsert_random_reject(&mut data, 3, 1);
        assert_eq!(data["StartDeal_3"]["RandomReject"], 1);
        assert_eq!(data["StartDeal_3"]["Chair0"], "");
    }

    // ---- 服务白名单 ----

    #[test]
    fn test_makecard_base_whitelist_and_derivation() {
        assert_eq!(
            makecard_base("D:/game", "xzmo"),
            Some(PathBuf::from("D:/game/xzmo/server_game"))
        );
        assert_eq!(
            makecard_base("D:/game", "xzmo2"),
            Some(PathBuf::from("D:/game/xzmo2/server_game"))
        );
        assert_eq!(makecard_base("D:/game", "zgda"), None, "白名单外不接受");
        assert_eq!(makecard_base("D:/game", "None"), None);
    }
}
