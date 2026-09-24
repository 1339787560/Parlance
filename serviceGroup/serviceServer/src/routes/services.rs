//! GET /api/services/status + GET /api/config/services/running
//!
//! status 走 TTL 缓存 (status_cache), 命中不重复 SCM syscall。running 端点
//! 额外过滤 configHide (配置编辑页不展示隐藏服务)。
//!
//! ports 字段 (Win32 only): 单次请求内一次性 snapshot 全进程 + IP Helper
//! 聚合 LISTEN 端口, 避免每服务 N 次 syscall (legacy psutil iter 慢源)。

use crate::error::{AppError, Result};
use crate::ports_probe::PortsProbe;
use crate::state::AppState;
use axum::extract::{ConnectInfo, Multipart, State};
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// 「最后更新」口径纳入的产物扩展名 (只看这些, 免得日志/缓存/临时文件扰动)。
const ARTIFACT_EXTS: &[&str] = &["exe", "pdb", "dll", "ini", "json", "lua", "html", "js", "css", "png"];

/// SystemTime → Unix 秒 (前端按本地时区格式化; Rust 侧不引日期库)。
fn epoch_secs(t: std::time::SystemTime) -> Option<u64> {
    t.duration_since(std::time::UNIX_EPOCH)
        .ok()
        .map(|d| d.as_secs())
}

/// 单文件 mtime (Unix 秒); 不存在/不可读 → None。
fn mtime_epoch(p: &std::path::Path) -> Option<u64> {
    std::fs::metadata(p).ok()?.modified().ok().and_then(epoch_secs)
}

/// 当前 Unix 秒 (操作 IP 记录用)。
fn now_epoch() -> u64 {
    epoch_secs(std::time::SystemTime::now()).unwrap_or(0)
}

/// 记「谁经本服务页操作了这个服务」。
///
/// **只在成功路径调用** —— 卡片要回答「谁最后把它动成功了」, 失败的尝试不留痕
/// (详见 [crate::op_ip] 头注)。取 IP 的口径见 `op_ip::client_ip`。
fn record_op(
    state: &AppState,
    service_id: &str,
    headers: &HeaderMap,
    peer: SocketAddr,
    action: &str,
) {
    let ip = crate::op_ip::client_ip(headers, Some(peer));
    state.op_ips.record(service_id, &ip, action, now_epoch());
}

/// 把「最后一次操作」三个字段挂到服务条目上 (无记录 → null, 前端渲染 "-")。
fn attach_last_op(entry: &mut Value, op: Option<&crate::op_ip::OpRecord>) {
    let Value::Object(m) = entry else { return };
    m.insert(
        "last_op_ip".into(),
        op.map(|r| json!(r.ip)).unwrap_or(Value::Null),
    );
    m.insert(
        "last_op_at".into(),
        op.map(|r| json!(r.at)).unwrap_or(Value::Null),
    );
    m.insert(
        "last_op_action".into(),
        op.map(|r| json!(r.action)).unwrap_or(Value::Null),
    );
}

/// 服务目录内**产物文件**的最晚修改时间 (非递归, 只 stat 一级文件)。
///
/// 「最后更新」= 该服务产物最近一次被写盘的时间: 整包直推 (非 exe 就地替换) 与
/// multipart 热更新都会刷新被替换文件的 mtime, 因此它就是「这服务上次被更新」。
/// 不看子目录 (日志/缓存/target 都在子目录或不在白名单内)。
fn newest_artifact_epoch(dir: &std::path::Path) -> Option<u64> {
    let mut newest: Option<u64> = None;
    for entry in std::fs::read_dir(dir).ok()?.flatten() {
        let p = entry.path();
        let ext_ok = p
            .extension()
            .and_then(|x| x.to_str())
            .map(|x| x.to_lowercase())
            .map(|x| ARTIFACT_EXTS.iter().any(|a| *a == x))
            .unwrap_or(false);
        if !ext_ok {
            continue;
        }
        if let Some(ts) = mtime_epoch(&p) {
            newest = Some(newest.map_or(ts, |n: u64| n.max(ts)));
        }
    }
    newest
}

/// GET /api/services/status — 全服务状态。
pub async fn list_status(State(state): State<AppState>) -> Result<Json<serde_json::Value>> {
    state.path_map.refresh(&state.config_path)?;
    let services = state.path_map.all();
    let provider = state.status_provider.as_ref();
    // ports 探测集合 (Win32 一次 snapshot + IP Helper; 非 windows 走 stub 空)。
    let ports_probe = PortsProbe::capture();
    // 键序即卡片顺序 —— 用 serde_json::Map (preserve_order 已开) 保序, 不用 BTreeMap
    // (BTreeMap 按 service_id 字典序重排, 是「改了 config.json 顺序也不生效」的旧根因)。
    // 顺序由 path_map.all() 给出 (= config.serviceOrder + 组名), 前端按对象键序分组渲染。
    //
    // service-server 自身也在这份陈列里 (自报, 不来自 config.json): 只提供「重启自身 +
    // 修改配置」两件事, 附 self:true 供前端渲染专用按钮 (停掉自己入口即消失; 换代必须走
    // deploy 包通道)。固定排在第一个面板, 故先插。
    let (self_id, mut self_entry) = self_service_entry();
    // 操作 IP 快照: 一次加锁取完, 下面逐服务查表 (2026-09-24 加)。
    let ops = state.op_ips.snapshot();
    attach_last_op(&mut self_entry, ops.get(&self_id));
    let mut map = serde_json::Map::new();
    map.insert(self_id, self_entry);
    for svc in services {
        let st = state
            .status_cache
            .get_or_query(&svc.service_id, provider);
        // shape 对齐 legacy Service.py get_all_service_status:
        //   status / type / exe / name / display_name / path / exe_path / ports
        //   + exe_mtime / updated_at (2026-09-21 加: 卡片展示「exe 修改时间 / 最后更新」,
        //     均为 Unix 秒, 前端本地化; None = 无该文件 / 目录不可读)
        //   + last_op_ip / last_op_at / last_op_action (2026-09-24 加: 卡片展示「最后操作 IP」,
        //     来源 = 经本页做服务生命周期操作的成功用户; None = 本机尚未有记录)
        let display_name = format!("同城游_{}_{}", svc.name, svc.svc_type);
        let exe_path = svc.path.join(&svc.exe);
        let ports = ports_str(st, &exe_path, &svc.exe, &ports_probe);
        let exe_mtime = mtime_epoch(&exe_path);
        let updated_at = newest_artifact_epoch(&svc.path);
        let mut entry = serde_json::json!({
            "status": st.label(),
            "type": svc.svc_type,
            "exe": svc.exe,
            "name": svc.name,
            "display_name": display_name,
            "path": svc.path.display().to_string(),
            "exe_path": exe_path.display().to_string(),
            "ports": ports,
            "exe_mtime": exe_mtime,
            "updated_at": updated_at,
        });
        // 「谁最后一次操作了这个服务」(2026-09-24 加)
        attach_last_op(&mut entry, ops.get(&svc.service_id));
        map.insert(svc.service_id.clone(), entry);
    }
    Ok(Json(Value::Object(map)))
}

/// 工具自身 (infoServer 子服务 serviceServer-rust) 的列表条目坐标。
///
/// 它不在 config.json 的游戏服务表里, 却要出现在同一份服务陈列中, 故由进程自报:
/// name = service-server, type = self → service_id = service-server_self。
pub const SELF_SERVICE_NAME: &str = "service-server";
pub const SELF_SERVICE_TYPE: &str = "self";
/// 工具自身监听端口 (main.rs 绑定的 :5000, 与 config.yaml serviceServer-rust.port 对齐)。
pub const SELF_SERVICE_PORT: u16 = 5000;

pub fn self_service_id() -> String {
    format!("{SELF_SERVICE_NAME}_{SELF_SERVICE_TYPE}")
}

/// 工具自身展示条目: 状态恒为「运行中」(本响应正由它发出), 端口与可执行文件自报。
fn self_service_entry() -> (String, serde_json::Value) {
    let exe_path = std::env::current_exe().unwrap_or_default();
    let path = exe_path
        .parent()
        .map(|p| p.display().to_string())
        .unwrap_or_default();
    let exe = exe_path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("service-server.exe")
        .to_string();
    // 时间字段与游戏服务同口径: exe mtime + 目录内产物最晚 mtime (换代/落位后立即反映)
    let exe_mtime = mtime_epoch(&exe_path);
    let updated_at = exe_path.parent().and_then(newest_artifact_epoch);
    let entry = serde_json::json!({
        "status": "运行中",
        "type": SELF_SERVICE_TYPE,
        "exe": exe,
        "name": SELF_SERVICE_NAME,
        "display_name": "service-server 工具自身",
        "path": path,
        "exe_path": exe_path.display().to_string(),
        "ports": SELF_SERVICE_PORT.to_string(),
        "exe_mtime": exe_mtime,
        "updated_at": updated_at,
        "self": true,
    });
    (self_service_id(), entry)
}

/// 按 status 语义决定 ports 字段串, 对齐 legacy Service.py 各分支。
/// - Running / 中间态 (启动中/停止中/已暂停) -> 查 pid 监听端口 CSV (空则 "未监听")
///   (中间态进程可能还在, 端口列照样有意义 —— 停止中往往就是"还占着端口但不干活")
/// - Stopped -> "未运行"
/// - NotFound / QueryFailed -> "未部署" (legacy 把 QueryServiceStatus 抛错归为未部署)
fn ports_str(
    st: crate::status::ServiceState,
    exe_path: &std::path::Path,
    exe: &str,
    probe: &PortsProbe,
) -> String {
    use crate::status::ServiceState::*;
    match st {
        Running | StartPending | StopPending | Paused => match probe.find_pid(exe, exe_path) {
            Some(pid) => {
                let ports = probe.ports_for_pid(pid);
                crate::ports_probe::format_ports_csv(&ports)
            }
            None => "未监听".to_string(),
        },
        Stopped => "未运行".to_string(),
        NotFound | QueryFailed => "未部署".to_string(),
    }
}

/// GET /api/config/services/running — 仅运行中服务 (configHide 过滤), 供配置编辑页。
pub async fn running_services(State(state): State<AppState>) -> Result<Json<serde_json::Value>> {
    state.path_map.refresh(&state.config_path)?;
    let services = state.path_map.all();
    // 同样保序 (配置编辑页下拉跟着卡片顺序走, 免得两处顺序打架)。
    let mut map = serde_json::Map::new();
    for svc in services {
        if state.path_map.is_hidden(&svc.name, &svc.svc_type) {
            continue;
        }
        let st = state
            .status_cache
            .get_or_query(&svc.service_id, state.status_provider.as_ref());
        if !st.is_running() {
            continue;
        }
        let display_name = format!("{} {}", svc.name, svc.exe);
        map.insert(
            svc.service_id.clone(),
            serde_json::json!({
                "name": display_name,
                "original_name": svc.name,
                "exe": svc.exe,
                "exe_name": svc.exe,
                "type": svc.svc_type,
                "path": svc.path.display().to_string(),
                "status": st.label(),
            }),
        );
    }
    Ok(Json(Value::Object(map)))
}

// ---- 控制: start / stop / restart / delete ----
//
// shape 对齐 legacy CustomRoute/ServiceRoute.py:
//   start {name,type,exe} -> {success,message} 异步 (立即返 "请求已提交")
//   stop  {name,type,exe} -> {success,message} 同步
//   restart {name,type,exe} -> {success,message} 异步
//   delete {name,type} -> {success,message} 同步
// service_name = "{name}_{type}" (Windows SCM 注册名)。

#[derive(Deserialize)]
pub struct ServiceReq {
    pub name: String,
    #[serde(rename = "type")]
    pub svc_type: String,
    pub exe: Option<String>,
}

impl ServiceReq {
    fn service_id(&self) -> String {
        format!("{}_{}", self.name, self.svc_type)
    }
}

/// POST /api/services/start — 异步: tokio task spawn_blocking 跑 SCM start,
/// 立即返 "请求已提交", 完成后 invalidate status_cache。
pub async fn start_service(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    // 工具自身由宿主管控, 不能走 SCM (它不是 Windows 服务); 要重启用「重启自身」。
    if req.svc_type == SELF_SERVICE_TYPE || req.name == SELF_SERVICE_NAME {
        return Ok(Json(json_err(
            400,
            "工具自身不支持手动启动: 它由 infoserver 宿主托管, 请用「重启自身」",
        )));
    }
    if req.exe.is_none() {
        return Ok(Json(json_err(400, "参数不完整")));
    }
    let id = req.service_id();
    record_op(&state, &id, &headers, peer, "start");
    let cache = state.status_cache.clone();
    let id_task = id.clone();
    tokio::task::spawn_blocking(move || {
        let _ = crate::svc_control::imp::start(&id_task);
        cache.invalidate(&id_task);
    });
    Ok(Json(serde_json::json!({
        "success": true,
        "message": "服务启动请求已提交",
    })))
}

/// POST /api/services/stop — 同步: ControlService STOP + 轮询 STOPPED (10s)。
pub async fn stop_service(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    // 停掉工具自身 = 入口消失 (且 enabled 由宿主托管), 故只允许「重启自身」;
    // 换代请走 deploy 包通道 (exe 必须经宿主 swap_exe)。
    if req.svc_type == SELF_SERVICE_TYPE || req.name == SELF_SERVICE_NAME {
        return Ok(Json(json_err(
            400,
            "工具自身不支持直接停止 (会导致入口消失): 请用「重启自身」或 deploy 包通道",
        )));
    }
    if req.exe.is_none() {
        return Ok(Json(json_err(400, "请提供可执行文件名")));
    }
    let id = req.service_id();
    let res = tokio::task::spawn_blocking(move || crate::svc_control::imp::stop(&id))
        .await
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
    state.status_cache.invalidate(&req.service_id());
    match res {
        Ok(msg) => {
            record_op(&state, &req.service_id(), &headers, peer, "stop");
            Ok(Json(serde_json::json!({ "success": true, "message": msg })))
        }
        Err(msg) => Ok(Json(serde_json::json!({ "success": false, "message": msg }))),
    }
}

/// POST /api/services/force-stop — 同步: 卡在 pending 时强杀进程兜底 (人工触发)。
///
/// 与 stop 的分工: stop 只发 SCM 停止指令 (优雅, 10s 轮询); force-stop 在优雅停不下来时
/// 按 exe 名+路径定位进程 TerminateProcess, 再等 SCM 收敛 —— **会丢未落盘数据**, 故只由
/// 前端「强制停止」按钮 (二次确认) 调用, 不在 update / stop 流程里自动触发。
pub async fn force_stop_service(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    // 工具自身不是 Windows 服务: 强杀它等于把自己入口干掉。
    if req.svc_type == SELF_SERVICE_TYPE || req.name == SELF_SERVICE_NAME {
        return Ok(Json(json_err(
            400,
            "工具自身不支持强制停止（它不是 Windows 服务）",
        )));
    }
    let exe = match &req.exe {
        Some(e) if !e.is_empty() => e.clone(),
        _ => return Ok(Json(json_err(400, "请提供可执行文件名"))),
    };
    state.path_map.refresh(&state.config_path)?;
    let abspath = state.path_map.abspath();
    let exe_path = exe_path(&abspath, &req.name, &req.svc_type, &exe);
    let id = req.service_id();
    let id_task = id.clone();
    let res = tokio::task::spawn_blocking(move || {
        crate::svc_control::imp::force_stop(&id_task, &exe, &exe_path)
    })
    .await
    .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
    state.status_cache.invalidate(&id);
    match res {
        Ok(msg) => {
            record_op(&state, &id, &headers, peer, "force-stop");
            Ok(Json(serde_json::json!({ "success": true, "message": msg })))
        }
        Err(msg) => Ok(Json(serde_json::json!({ "success": false, "message": msg }))),
    }
}

/// POST /api/services/restart — 异步: stop -> sleep 2s -> start, 立即返。
pub async fn restart_service(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    // 工具自身: 既不是 Windows 服务 (走不了 SCM), 也不能自杀式就地换代 ——
    // 交 legacy 经宿主管道 restart (stop_verified 端口判据 → start, 句柄留宿主),
    // 响应由 legacy 发出, 本进程随后才被停, 故调用方拿得到回包。
    if req.svc_type == SELF_SERVICE_TYPE || req.name == SELF_SERVICE_NAME {
        let id = req.service_id();
        let resp = self_restart_via_legacy(&state).await?;
        // 只记成功: 委派失败 = 这次重启并未发生
        if resp.0.get("success").and_then(Value::as_bool) == Some(true) {
            record_op(&state, &id, &headers, peer, "restart");
        }
        return Ok(resp);
    }
    if req.exe.is_none() {
        return Ok(Json(json_err(400, "参数不完整（需要 name, type, exe）")));
    }
    let id = req.service_id();
    record_op(&state, &id, &headers, peer, "restart");
    let cache = state.status_cache.clone();
    let id_task = id.clone();
    tokio::task::spawn_blocking(move || {
        let _ = crate::svc_control::imp::stop(&id_task);
        std::thread::sleep(std::time::Duration::from_secs(2));
        let _ = crate::svc_control::imp::start(&id_task);
        cache.invalidate(&id_task);
    });
    Ok(Json(serde_json::json!({
        "success": true,
        "message": "服务重启请求已提交（停止 → 等待 → 启动）",
    })))
}

/// 工具自身重启: 委派发布面 `POST /api/deploy/self-restart`, 由它请求宿主 restart。
///
/// 2026-09-22 起发布面在 **L2 (run.py) 的 :5099** (原 legacy Flask 让位 5098) ——
/// 委派目标 = `state.deploy_url`: 发布面本身不在被重启目标内, 故停机窗口仍能应答。
/// (U8 收口后 `legacy_backend` 已随反代 fallback 一并删除, 本函数名保留历史。) 
///
/// 为什么不自己做: ① 重启要停掉本进程, HTTP 回包必须由别人发出; ② 停/起必须经宿主
/// 持句柄 (谁 Popen 谁持句柄铁律), 否则 :5000 退化成孤儿进程 —— 孤儿既停不掉也换不了
/// exe (2026-09-13 堡垒机事故根因)。
async fn self_restart_via_legacy(state: &AppState) -> Result<Json<serde_json::Value>> {
    let url = format!(
        "{}/api/deploy/self-restart",
        state.deploy_url.trim_end_matches('/')
    );
    // reqwest 未开 json feature (Cargo.toml default-features=false) → 手写 JSON 体。
    let payload = format!(r#"{{"port":{SELF_SERVICE_PORT}}}"#);
    let sent = state
        .http_client
        .post(&url)
        .header(reqwest::header::CONTENT_TYPE, "application/json")
        .body(payload)
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .await;
    match sent {
        Ok(resp) => {
            let status = resp.status();
            let text = resp.text().await.unwrap_or_default();
            if status.is_success() {
                Ok(Json(serde_json::json!({
                    "success": true,
                    "message": "工具自身重启已提交（经宿主 停→起, 约 5-10 秒后刷新）",
                })))
            } else {
                Ok(Json(json_err(
                    502,
                    &format!("legacy 拒绝重启请求: HTTP {status} {text}"),
                )))
            }
        }
        Err(e) => Ok(Json(json_err(
            502,
            &format!("委派 legacy 失败 (legacy {url} 是否在线?): {e}"),
        ))),
    }
}

/// POST /api/services/delete — 同步: DeleteService (SCM 注销)。
pub async fn delete_service(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(req): Json<ServiceReq>,
) -> Result<Json<serde_json::Value>> {
    let id = req.service_id();
    let res = tokio::task::spawn_blocking(move || crate::svc_control::imp::delete(&id))
        .await
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
    state.status_cache.invalidate(&req.service_id());
    match res {
        Ok(msg) => {
            record_op(&state, &req.service_id(), &headers, peer, "delete");
            Ok(Json(serde_json::json!({ "success": true, "message": msg })))
        }
        Err(msg) => Ok(Json(serde_json::json!({ "success": false, "message": msg }))),
    }
}

fn json_err(code: u16, msg: &str) -> serde_json::Value {
    serde_json::json!({ "success": false, "message": msg, "_status": code })
}

// ---- deploy / start-all / update ----
//
// 对齐 legacy CustomRoute/ServiceRoute.py:
//   deploy    {name,type,exe} -> 校验 exe 存在 + config 加条目 + sc create, 返 {success,message}
//   start-all (无 body) -> 后台按序启动, 立即返 "所有服务已开始启动"
//   update    multipart(name/type/exe + file_exe/file_pdb) -> 停 -> 替换 -> 启, 同步返

/// POST /api/services/deploy — 部署服务。
pub async fn deploy_service(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Json(req): Json<ServiceReq>,
) -> Result<(StatusCode, Json<Value>)> {
    let exe = match &req.exe {
        Some(e) if !e.is_empty() => e.clone(),
        _ => {
            return Ok((
                StatusCode::BAD_REQUEST,
                Json(json!({ "success": false, "message": "参数不完整" })),
            ))
        }
    };
    state.path_map.refresh(&state.config_path)?;
    let abspath = state.path_map.abspath();
    let service_path = exe_path(&abspath, &req.name, &req.svc_type, &exe);
    if !service_path.exists() {
        return Ok((
            StatusCode::OK,
            Json(json!({
                "success": false,
                "message": format!("服务文件不存在: {}", service_path.display())
            })),
        ));
    }
    // 配置加条目 (type 已存在则跳过, 对齐 legacy 逻辑), 变更才回写。
    let mut config = crate::routes::read_config_value(&state.config_path)?;
    if ensure_service_entry(&mut config, &req.name, &req.svc_type, &exe) {
        crate::routes::write_config_value(&state.config_path, &config)?;
    }
    // sc create 注册 Windows 服务 (对齐 legacy os.popen('sc create ...'))。
    let service_name = req.service_id();
    let display = display(&service_name);
    let registered = sc_create(&service_name, &service_path.display().to_string(), &display);
    let message = if registered {
        format!("服务 {display} 已成功部署到 {}，并已注册为Windows服务", req.name)
    } else {
        format!("服务 {display} 已成功部署到 {}（配置已添加，但未注册为Windows服务）", req.name)
    };
    record_op(&state, &service_name, &headers, peer, "deploy");
    Ok((StatusCode::OK, Json(json!({ "success": true, "message": message }))))
}

/// POST /api/services/start-all — 后台按序启动, 立即返 (对齐 legacy daemon thread)。
pub async fn start_all_services(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
) -> Result<(StatusCode, Json<Value>)> {
    // 「一键启动全部」也是经本页的操作: 给本次陈列的每个服务各记一条 (同 IP / 时间 / 动作)。
    let op_ip = crate::op_ip::client_ip(&headers, Some(peer));
    let op_at = now_epoch();
    if state.path_map.refresh(&state.config_path).is_ok() {
        for svc in state.path_map.all() {
            state.op_ips.record(&svc.service_id, &op_ip, "start-all", op_at);
        }
    }
    let config_path = state.config_path.clone();
    let path_map = state.path_map.clone();
    tokio::task::spawn_blocking(move || {
        if let Err(e) = run_start_all(&config_path, &path_map) {
            tracing::warn!("start-all 执行失败: {e}");
        }
    });
    Ok((
        StatusCode::OK,
        Json(json!({ "success": true, "message": "所有服务已开始启动，请稍后查看状态" })),
    ))
}

/// POST /api/services/update — multipart 上传 exe/pdb 热更新 (停 -> 替换 -> 启)。
pub async fn update_service(
    State(state): State<AppState>,
    ConnectInfo(peer): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    mut multipart: Multipart,
) -> Result<(StatusCode, Json<Value>)> {
    let mut name: Option<String> = None;
    let mut svc_type: Option<String> = None;
    let mut exe: Option<String> = None;
    let mut file_exe: Option<(String, Vec<u8>)> = None;
    let mut file_pdb: Option<(String, Vec<u8>)> = None;

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?
    {
        let field_name = field.name().unwrap_or("").to_string();
        match field_name.as_str() {
            "name" => name = Some(field.text().await.map_err(mp_err)?),
            "type" => svc_type = Some(field.text().await.map_err(mp_err)?),
            "exe" => exe = Some(field.text().await.map_err(mp_err)?),
            "file_exe" => {
                let fname = field.file_name().unwrap_or("").to_string();
                let bytes = field.bytes().await.map_err(mp_err)?.to_vec();
                file_exe = Some((fname, bytes));
            }
            "file_pdb" => {
                let fname = field.file_name().unwrap_or("").to_string();
                let bytes = field.bytes().await.map_err(mp_err)?.to_vec();
                file_pdb = Some((fname, bytes));
            }
            _ => {}
        }
    }

    let name = match name {
        Some(n) => n,
        None => return Ok(upd_err("参数不完整（需要 name, type, exe）")),
    };
    let svc_type = match svc_type {
        Some(t) => t,
        None => return Ok(upd_err("参数不完整（需要 name, type, exe）")),
    };
    let exe = match exe {
        Some(e) => e,
        None => return Ok(upd_err("参数不完整（需要 name, type, exe）")),
    };

    // 上传文件校验 (对齐 legacy ServiceRoute.api_update_service)。
    let (exe_fname, exe_bytes) = match file_exe {
        Some(v) => v,
        None => return Ok(upd_err("未找到上传的 .exe 文件")),
    };
    let (pdb_fname, pdb_bytes) = match file_pdb {
        Some(v) => v,
        None => return Ok(upd_err("未找到上传的 .pdb 文件")),
    };
    if exe_fname.is_empty() {
        return Ok(upd_err("未选择 .exe 文件"));
    }
    if pdb_fname.is_empty() {
        return Ok(upd_err("未选择 .pdb 文件"));
    }
    if exe_fname.to_lowercase() != exe.to_lowercase() {
        return Ok(upd_err(&format!(
            "上传的 .exe 文件名 {} 与配置的 {} 不匹配",
            exe_fname, exe
        )));
    }
    if stem_lower(&exe_fname) != stem_lower(&pdb_fname) {
        return Ok(upd_err(&format!(
            "上传的 .exe 文件 ({exe_fname}) 和 .pdb 文件 ({pdb_fname}) 的基本文件名不匹配"
        )));
    }

    // state 随后被 move 进阻塞任务, 故提前取出记录入口 + 操作者 IP。
    let op_ips = state.op_ips.clone();
    let op_id = format!("{name}_{svc_type}");
    let op_ip = crate::op_ip::client_ip(&headers, Some(peer));
    let res = tokio::task::spawn_blocking(move || {
        do_update(&state, &name, &svc_type, &exe, &exe_bytes, &pdb_bytes)
    })
    .await
    .map_err(|e| AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;
    let (success, message) = res;
    if success {
        op_ips.record(&op_id, &op_ip, "update", now_epoch());
    }
    Ok((StatusCode::OK, Json(json!({ "success": success, "message": message }))))
}

// ---- 内部实现 ----

/// abspath/name/type/exe 完整路径 (对齐 legacy os.path.join + normpath)。
fn exe_path(abspath: &str, name: &str, svc_type: &str, exe: &str) -> PathBuf {
    PathBuf::from(abspath).join(name).join(svc_type).join(exe)
}

/// 文件名去扩展名 (对齐 legacy os.path.splitext()[0].lower())。
fn stem_lower(fname: &str) -> String {
    PathBuf::from(fname)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(fname)
        .to_lowercase()
}

/// config 中确保 name 组与 {type,exe} 条目存在; 返回是否发生了变更。
/// 对齐 legacy deploy_service: name 不存在则建空组; type 已存在则不动。
fn ensure_service_entry(config: &mut Value, name: &str, svc_type: &str, exe: &str) -> bool {
    if config.get("service").and_then(|s| s.as_object()).is_none() {
        config["service"] = Value::Object(Default::default());
    }
    let services = config["service"].as_object_mut().unwrap();
    let list = services.entry(name.to_string()).or_insert_with(|| Value::Array(vec![]));
    let arr = match list.as_array_mut() {
        Some(a) => a,
        None => {
            *list = Value::Array(vec![]);
            list.as_array_mut().unwrap()
        }
    };
    let exists = arr
        .iter()
        .any(|e| e.get("type").and_then(|t| t.as_str()) == Some(svc_type));
    if exists {
        return false;
    }
    arr.push(json!({ "type": svc_type, "exe": exe }));
    true
}

/// sc create 注册 Windows 服务。主判据 exit code 0 (sc 输出是控制台 OEM 编码,
/// 中文 "成功" 检测不可靠), 辅判据 stdout 含 "SUCCESS"。
fn sc_create(service_name: &str, bin_path: &str, display_name: &str) -> bool {
    let out = std::process::Command::new("sc")
        .args([
            "create",
            service_name,
            &format!("binPath={bin_path}"),
            &format!("DisplayName={display_name}"),
            "start=",
            "demand",
        ])
        .output();
    match out {
        Ok(o) => {
            o.status.success()
                || String::from_utf8_lossy(&o.stdout).to_uppercase().contains("SUCCESS")
        }
        Err(_) => false,
    }
}

/// start-all 后台主体。读取 script.json 决定顺序 (对齐 legacy start_all_services):
/// - script.json 缺失/空对象 -> 按 config.json service 顺序全启
/// - 否则按 start_order 数组 (当前 script.json 只有 scripts[], 无 start_order -> 启动 0 个, 与 legacy 现状一致)
fn run_start_all(
    config_path: &std::path::Path,
    path_map: &crate::path_map::PathMap,
) -> Result<()> {
    path_map.refresh(config_path)?;
    let config = crate::routes::read_config_value(config_path)?;
    match read_script_order(config_path) {
        None => {
            for (name, svc_type, exe) in collect_config_order(&config) {
                start_one(&name, &svc_type, &exe);
            }
        }
        Some(names) => {
            let service = config.get("service").and_then(|s| s.as_object());
            for name in names {
                match service.and_then(|s| s.get(&name)).and_then(|l| l.as_array()) {
                    Some(list) => {
                        for entry in list {
                            if let (Some(t), Some(e)) = (
                                entry.get("type").and_then(|v| v.as_str()),
                                entry.get("exe").and_then(|v| v.as_str()),
                            ) {
                                start_one(&name, t, e);
                            }
                        }
                    }
                    None => tracing::warn!("start-all: 服务组 {name} 不存在"),
                }
            }
        }
    }
    Ok(())
}

/// 读 script.json 启动顺序: None=走 config 默认顺序, Some=start_order 数组。
/// 缺省文件/空对象 -> None (对齐 legacy `if not script`); 有键但无 start_order -> Some(空)。
fn read_script_order(config_path: &std::path::Path) -> Option<Vec<String>> {
    let script_path = config_path.parent().map(|p| p.join("script.json"))?;
    let raw = match std::fs::read_to_string(&script_path) {
        Ok(r) => r,
        Err(_) => return None,
    };
    let script: Value = serde_json::from_str(&raw).ok()?;
    if script.is_null() || script.as_object().map(|o| o.is_empty()).unwrap_or(false) {
        return None;
    }
    Some(
        script
            .get("start_order")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default(),
    )
}

/// config.json service 段按 JSON 键序收集 (name,type,exe)。
fn collect_config_order(config: &Value) -> Vec<(String, String, String)> {
    let mut out = Vec::new();
    if let Some(obj) = config.get("service").and_then(|s| s.as_object()) {
        for (name, list) in obj {
            if let Some(arr) = list.as_array() {
                for entry in arr {
                    if let (Some(t), Some(e)) = (
                        entry.get("type").and_then(|v| v.as_str()),
                        entry.get("exe").and_then(|v| v.as_str()),
                    ) {
                        out.push((name.clone(), t.to_string(), e.to_string()));
                    }
                }
            }
        }
    }
    out
}

fn start_one(name: &str, svc_type: &str, exe: &str) {
    let id = format!("{name}_{svc_type}");
    match crate::svc_control::imp::start(&id) {
        Ok(m) => tracing::info!("start-all {id} (exe={exe}): {m}"),
        Err(m) => tracing::warn!("start-all {id} (exe={exe}): {m}"),
    }
}

/// 热更新主体 (阻塞): 查中间态 -> 停 -> 等到 exe 可写 -> 替换 exe/pdb -> 启。
///
/// 2026-09-23 加固 (chunksvr 上传踩坑):
/// ① pending 态 (停止中/启动中/已暂停) 前置拒绝 —— 别在服务本来就卡着时再制造一次半停机;
/// ② 固定 sleep 2s 换成 wait_writable 轮询: Windows 释放被停进程的 image section 有延迟
///    (实测偶发 >2s), 固定 sleep 赌不过去, 写 exe 直接撞 Error 32;
/// ③ 停止成功但替换失败时, 用旧 exe 把服务拉回运行 —— 不留"停了就不管"的停机现场。
fn do_update(
    state: &AppState,
    name: &str,
    svc_type: &str,
    exe: &str,
    exe_bytes: &[u8],
    pdb_bytes: &[u8],
) -> (bool, String) {
    let _ = state.path_map.refresh(&state.config_path);
    let abspath = state.path_map.abspath();
    let exe_path = exe_path(&abspath, name, svc_type, exe);
    if !exe_path.exists() {
        return (false, format!("服务文件不存在，无法更新: {}", exe_path.display()));
    }
    let pdb_path = exe_path.with_extension("pdb");
    let id = format!("{name}_{svc_type}");
    let display = display(&id);
    // 0. 中间态前置拒绝: 已经卡着的服务先让人处理 (强制停止), 不在这里二次踩踏。
    let st = state.status_provider.query(&id);
    if st.is_pending() {
        return (
            false,
            format!(
                "服务 {display} 当前处于「{}」, 请等它稳定或用「强制停止」后再上传",
                st.label()
            ),
        );
    }
    // 1. 停服务 (已停止/不存在视为成功, 对齐 legacy 文案白名单)。
    if let Err(m) = crate::svc_control::imp::stop(&id) {
        if !["不存在", "已经停止", "未找到"].iter().any(|k| m.contains(k)) {
            // 停不下来最常见的是卡在 STOP_PENDING (进程不响应停止指令): 点明当前状态 + 给出出路,
            // 别只丢一句「停止服务失败」让人猜 (2026-09-23: chunksvr 上传报的就是这个症状)。
            let now = state.status_provider.query(&id);
            if now.is_pending() {
                return (
                    false,
                    format!(
                        "服务 {display} 卡在「{}」（进程未响应停止指令），未替换文件；请用卡片上的「强制停止」后再上传",
                        now.label()
                    ),
                );
            }
            return (false, format!("停止服务失败，无法更新: {m}"));
        }
    }
    state.status_cache.invalidate(&id);
    // 2. 等 exe 真能打开写句柄 (替代固定 sleep 2s)。
    if !wait_writable(&exe_path, Duration::from_secs(20)) {
        return (
            false,
            format!(
                "exe 仍被占用（进程未完全退出），未替换文件; {}",
                recover_after_failed_update(state, &id, &display)
            ),
        );
    }
    // 3. 替换文件 (legacy 用 open 'wb' 直接覆盖, 停服后无 busy 冲突)。
    if let Err(e) = std::fs::write(&exe_path, exe_bytes) {
        return (
            false,
            format!(
                "替换文件时发生错误: {e}; {}",
                recover_after_failed_update(state, &id, &display)
            ),
        );
    }
    if let Err(e) = std::fs::write(&pdb_path, pdb_bytes) {
        return (
            false,
            format!(
                "替换文件时发生错误: {e}; {}",
                recover_after_failed_update(state, &id, &display)
            ),
        );
    }
    // 4. 重启。
    let res = match crate::svc_control::imp::start(&id) {
        Ok(_) => (true, format!("服务 {display} 更新并启动成功")),
        Err(m) => (true, format!("服务 {display} 文件已更新，但启动失败: {m}")),
    };
    state.status_cache.invalidate(&id);
    res
}

/// 替换失败后的收尾: 用旧 exe 把服务拉回运行, 不留"停了就不管"的停机现场。
fn recover_after_failed_update(state: &AppState, id: &str, display: &str) -> String {
    let note = match crate::svc_control::imp::start(id) {
        Ok(_) => format!("已把服务 {display} 用原文件拉回运行"),
        Err(m) => format!("且拉回启动失败: {m}（服务当前为停止状态，请手动启动）"),
    };
    state.status_cache.invalidate(id);
    note
}

/// 轮询到能给 path 打开写句柄 (或超时/文件不存在)。
///
/// 用途: 判断被停进程是否已释放 exe 的 image section —— Windows 上这件事有延迟 (实测偶发
/// 14s 量级), 固定 sleep 赌不过去 (与 infoserver 宿主 swap_exe 的 wait_writable 同一教训)。
fn wait_writable(path: &Path, timeout: Duration) -> bool {
    let start = Instant::now();
    loop {
        match std::fs::OpenOptions::new().write(true).open(path) {
            Ok(_) => return true,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return false,
            Err(_) if start.elapsed() >= timeout => return false,
            Err(_) => std::thread::sleep(Duration::from_millis(300)),
        }
    }
}

fn upd_err(msg: &str) -> (StatusCode, Json<Value>) {
    (StatusCode::BAD_REQUEST, Json(json!({ "success": false, "message": msg })))
}

fn mp_err(e: axum::extract::multipart::MultipartError) -> AppError {
    AppError::Io(std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;
    use serde_json::json;
    use tempfile::tempdir;

    #[rstest]
    #[case("Game.exe", "game")]
    #[case("Game.EXE", "game")]
    #[case("roomsvr", "roomsvr")]
    #[case("", "")]
    fn test_stem_lower(#[case] input: &str, #[case] expected: &str) {
        assert_eq!(stem_lower(input), expected);
    }

    /// ensure_service_entry: 新组建组 + 加条目; 已有 type 不动; 返回变更标志。
    #[test]
    fn test_ensure_service_entry() {
        let mut config = json!({ "service": { "xzmo": [{ "type": "server_game", "exe": "A.exe" }] } });
        // 新组
        assert!(ensure_service_entry(&mut config, "zgda", "server_room", "R.exe"));
        assert_eq!(
            config["service"]["zgda"][0],
            json!({ "type": "server_room", "exe": "R.exe" })
        );
        // 已有 type -> 不变更
        assert!(!ensure_service_entry(&mut config, "xzmo", "server_game", "B.exe"));
        assert_eq!(config["service"]["xzmo"].as_array().unwrap().len(), 1);
        // 新 type 追加
        assert!(ensure_service_entry(&mut config, "xzmo", "server_chunk", "C.exe"));
        assert_eq!(config["service"]["xzmo"].as_array().unwrap().len(), 2);
    }

    /// collect_config_order: 按 JSON 键序展开 service 段。
    #[test]
    fn test_collect_config_order() {
        let config = json!({
            "service": {
                "zgda": [{ "type": "server_room", "exe": "R.exe" }],
                "xzmo": [
                    { "type": "server_game", "exe": "G.exe" },
                    { "type": "server_chunk", "exe": "C.exe" }
                ]
            }
        });
        assert_eq!(
            collect_config_order(&config),
            vec![
                ("zgda".into(), "server_room".into(), "R.exe".into()),
                ("xzmo".into(), "server_game".into(), "G.exe".into()),
                ("xzmo".into(), "server_chunk".into(), "C.exe".into()),
            ]
        );
    }

    /// read_script_order: 缺文件/空对象 -> None (config 默认序); 有键无 start_order -> Some(空);
    /// 有 start_order -> Some(名称列表)。
    #[test]
    fn test_read_script_order() {
        let dir = tempdir().unwrap();
        let config = dir.path().join("config.json");
        std::fs::write(&config, "{}").unwrap();
        // 无 script.json
        assert!(read_script_order(&config).is_none());
        // 空对象
        std::fs::write(dir.path().join("script.json"), "{}").unwrap();
        assert!(read_script_order(&config).is_none());
        // 有键无 start_order (当前生产 script.json 形态: 只有 scripts[])
        std::fs::write(
            dir.path().join("script.json"),
            json!({ "scripts": [{ "name": "x", "sequence": [] }] }).to_string(),
        )
        .unwrap();
        assert_eq!(read_script_order(&config), Some(vec![]));
        // 有 start_order
        std::fs::write(
            dir.path().join("script.json"),
            json!({ "start_order": ["zgda", "xzmo"] }).to_string(),
        )
        .unwrap();
        assert_eq!(read_script_order(&config), Some(vec!["zgda".into(), "xzmo".into()]));
    }

    /// sc_create 外部副作用不测; 这里仅锁死 deploy 的路径拼装。
    #[test]
    fn test_exe_path_join() {
        assert_eq!(
            exe_path("D:/game/", "xzmo", "server_game", "xzmoSvr.exe"),
            PathBuf::from("D:/game/xzmo/server_game/xzmoSvr.exe")
        );
    }

    /// 「最后更新」口径矩阵: 只认产物扩展名, 更新的非产物文件 (日志) 不得抬高结果。
    #[test]
    fn test_newest_artifact_epoch_ignores_non_artifact_newer_file() {
        // Arrange: exe → sleep → html → sleep → log (log 最新, 但不在白名单)
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("svc.exe"), b"x").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(30));
        std::fs::write(dir.path().join("page.html"), b"y").unwrap();
        let html_ts = mtime_epoch(&dir.path().join("page.html")).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(30));
        std::fs::write(dir.path().join("svc.log"), b"z").unwrap();

        // Act
        let got = newest_artifact_epoch(dir.path());

        // Assert: 取 html 的 mtime, 不被更新的 log 抬高
        assert_eq!(got, Some(html_ts));
    }

    /// 空目录 → None (卡片显示「—」)。
    #[test]
    fn test_newest_artifact_epoch_empty_dir_is_none() {
        // Arrange
        let dir = tempfile::tempdir().unwrap();

        // Act + Assert
        assert_eq!(newest_artifact_epoch(dir.path()), None);
    }

    /// exe 不存在时 mtime 为 None (未部署服务的卡片不得显示假时间)。
    #[test]
    fn test_mtime_epoch_missing_file_is_none() {
        // Arrange
        let dir = tempfile::tempdir().unwrap();

        // Act + Assert
        assert_eq!(mtime_epoch(&dir.path().join("nope.exe")), None);
    }

    /// wait_writable: 可写文件立即通过; 缺失路径立即失败 (不空等到超时)。
    #[test]
    fn test_wait_writable_probe() {
        // Arrange
        let dir = tempfile::tempdir().unwrap();
        let ok = dir.path().join("ok.exe");
        std::fs::write(&ok, b"x").unwrap();

        // Act + Assert: 可写 -> true; 不存在 -> 立即 false (不是等满超时)
        assert!(wait_writable(&ok, Duration::from_millis(200)));
        let t0 = Instant::now();
        assert!(!wait_writable(&dir.path().join("nope.exe"), Duration::from_millis(5000)));
        assert!(
            t0.elapsed() < Duration::from_secs(1),
            "缺失文件必须立即返回, 不该空等: {:?}",
            t0.elapsed()
        );
    }
}

fn display(service_id: &str) -> String {
    if let Some(idx) = service_id.find('_') {
        let (name, t) = service_id.split_at(idx);
        format!("同城游_{}{}", name, t)
    } else {
        service_id.to_string()
    }
}

// 静默 StatusCode 占位 (json_err 返 _status 字段供 caller 选用, handler 当前都用 200
// 对齐 legacy 默认 200 文案模式; 此处保 StatusCode import 不被裁)
#[allow(dead_code)]
fn _silence_statuscode() -> StatusCode {
    StatusCode::OK
}
