//! Win32 SCM 服务控制 (启动 / 停止 / 删除)。
//!
//! 对应 legacy Service.py start_service_pywin32 / stop_service_pywin32 /
//! delete_service。OpenSCManager -> OpenService -> op -> poll (10s) -> CloseHandle。
//!
//! 不做 install-on-missing (start 分支): legacy 在 start 时若服务未装会先 InstallService,
//! Rust 简化为未装直接报错 -> 前端走 /deploy (仍 legacy 反代)。strangler 渐进。

use std::time::{Duration, Instant};

use windows::core::PCWSTR;
use windows::Win32::System::Services::{
    CloseServiceHandle, ControlService, DeleteService, OpenSCManagerW, OpenServiceW,
    QueryServiceStatus, StartServiceW, SERVICE_CONTROL_STOP, SERVICE_RUNNING, SERVICE_STATUS,
    SERVICE_STOPPED, SC_MANAGER_CONNECT, SERVICE_QUERY_STATUS, SERVICE_START, SERVICE_STOP,
};

/// DELETE 访问位 (Win32 标准 0x00010000, windows crate 把 DELETE 常量放
/// Storage::FileSystem::FILE_ACCESS_RIGHTS, 引入整 feature 不值, 用裸 u32)。
const SC_DELETE_ACCESS: u32 = 0x0001_0000;

use crate::status::{ServiceState, ServiceStatusProvider};

/// 启动服务: StartServiceW 后轮询 dwCurrentState==RUNNING, 最长 10s。
/// 未部署 / 启动失败 / 超时 -> Err(中文消息)。成功 -> Ok(消息)。
pub fn start_service(service_name: &str) -> Result<String, String> {
    let display = display_name(service_name);
    let wide = wide(service_name);
    unsafe {
        let scm = match OpenSCManagerW(PCWSTR::null(), PCWSTR::null(), SC_MANAGER_CONNECT) {
            Ok(h) => h,
            Err(_) => return Err(format!("打开 SCManager 失败")),
        };
        let svc = match OpenServiceW(scm, PCWSTR(wide.as_ptr()), SERVICE_START | SERVICE_QUERY_STATUS) {
            Ok(h) => h,
            Err(_) => {
                let _ = CloseServiceHandle(scm);
                return Err(format!("服务 {display} 未部署或无法访问"));
            }
        };
        let rc = StartServiceW(svc, None);
        if rc.is_err() {
            let already_running = matches!(query(svc), Some(ServiceState::Running));
            let _ = CloseServiceHandle(svc);
            let _ = CloseServiceHandle(scm);
            if already_running {
                return Ok(format!("服务 {display} 已经在运行，跳过启动"));
            }
            return Err(format!("启动服务 {display} 失败"));
        }
        let ok = poll_state(svc, SERVICE_RUNNING.0, Duration::from_secs(10));
        let _ = CloseServiceHandle(svc);
        let _ = CloseServiceHandle(scm);
        if ok {
            Ok(format!("服务 {display} 启动成功"))
        } else {
            Err(format!("服务 {display} 启动超时，等待了10秒未检测到运行状态"))
        }
    }
}

/// 停止服务: ControlService(STOP) 后轮询 STOPPED, 最长 10s。
/// 已停止 / 未部署 -> Ok(说明消息)。
pub fn stop_service(service_name: &str) -> Result<String, String> {
    let display = display_name(service_name);
    let wide = wide(service_name);
    unsafe {
        let scm = match OpenSCManagerW(PCWSTR::null(), PCWSTR::null(), SC_MANAGER_CONNECT) {
            Ok(h) => h,
            Err(_) => return Err(format!("打开 SCManager 失败")),
        };
        let svc = match OpenServiceW(scm, PCWSTR(wide.as_ptr()), SERVICE_STOP | SERVICE_QUERY_STATUS) {
            Ok(h) => h,
            Err(_) => {
                let _ = CloseServiceHandle(scm);
                return Ok(format!("服务 {display} 不存在，无需停止"));
            }
        };
        let mut status = SERVICE_STATUS::default();
        if QueryServiceStatus(svc, &mut status).is_ok()
            && status.dwCurrentState == SERVICE_STOPPED
        {
            let _ = CloseServiceHandle(svc);
            let _ = CloseServiceHandle(scm);
            return Ok(format!("服务 {display} 已经停止"));
        }
        if ControlService(svc, SERVICE_CONTROL_STOP, &mut status).is_err() {
            let _ = CloseServiceHandle(svc);
            let _ = CloseServiceHandle(scm);
            return Err(format!("停止服务 {display} 失败"));
        }
        let ok = poll_state(svc, SERVICE_STOPPED.0, Duration::from_secs(10));
        let _ = CloseServiceHandle(svc);
        let _ = CloseServiceHandle(scm);
        if ok {
            Ok(format!("服务 {display} 停止成功"))
        } else {
            Err(format!("服务 {display} 停止超时，等待了10秒未检测到停止状态"))
        }
    }
}

/// 删除服务 (SCM 注销, 不删盘文件): DeleteService。
/// 未部署 -> Ok(说明消息)。
pub fn delete_service(service_name: &str) -> Result<String, String> {
    let display = display_name(service_name);
    let wide = wide(service_name);
    unsafe {
        let scm = match OpenSCManagerW(PCWSTR::null(), PCWSTR::null(), SC_MANAGER_CONNECT) {
            Ok(h) => h,
            Err(_) => return Err(format!("打开 SCManager 失败")),
        };
        let svc = match OpenServiceW(scm, PCWSTR(wide.as_ptr()), SC_DELETE_ACCESS | SERVICE_QUERY_STATUS) {
            Ok(h) => h,
            Err(_) => {
                let _ = CloseServiceHandle(scm);
                return Ok(format!("服务 {display} 不存在，无需删除"));
            }
        };
        let rc = DeleteService(svc);
        let _ = CloseServiceHandle(svc);
        let _ = CloseServiceHandle(scm);
        if rc.is_ok() {
            Ok(format!("服务 {display} 已成功从 SCM 注销"))
        } else {
            Err(format!("删除服务 {display} 失败"))
        }
    }
}

// ---- helpers ----

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// 服务显示名, 对齐 legacy get_service_display_name。
/// service_name 形如 "{name}_{type}" -> "同城游_{name}_{type}"。
fn display_name(service_name: &str) -> String {
    if let Some(idx) = service_name.find('_') {
        let (name, type_name) = service_name.split_at(idx);
        let type_name = &type_name[1..];
        format!("同城游_{name}_{type_name}")
    } else {
        service_name.to_string()
    }
}

/// 单服务 QueryServiceStatus -> ServiceState (复用 status crate 语义)。
unsafe fn query(svc: windows::Win32::System::Services::SC_HANDLE) -> Option<ServiceState> {
    let mut status = SERVICE_STATUS::default();
    if QueryServiceStatus(svc, &mut status).is_err() {
        return None;
    }
    Some(match status.dwCurrentState {
        s if s == SERVICE_RUNNING => ServiceState::Running,
        s if s == SERVICE_STOPPED => ServiceState::Stopped,
        _ => ServiceState::QueryFailed,
    })
}

/// 轮询 QueryServiceStatus 直到 dwCurrentState.0 == target 或超时。
unsafe fn poll_state(
    svc: windows::Win32::System::Services::SC_HANDLE,
    target: u32,
    timeout: Duration,
) -> bool {
    let start = Instant::now();
    let mut status = SERVICE_STATUS::default();
    while start.elapsed() < timeout {
        std::thread::sleep(Duration::from_millis(500));
        if QueryServiceStatus(svc, &mut status).is_err() {
            return false;
        }
        if status.dwCurrentState.0 == target {
            return true;
        }
    }
    false
}
