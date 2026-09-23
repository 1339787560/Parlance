//! Win32 SCM 服务控制 (启动 / 停止 / 强制停止 / 删除)。
//!
//! 对应 legacy Service.py start_service_pywin32 / stop_service_pywin32 /
//! delete_service。OpenSCManager -> OpenService -> op -> poll (10s) -> CloseHandle。
//!
//! 强制停止 (2026-09-23): SCM 卡在 STOP_PENDING 时优雅停止永远等不到 —— 按 exe 名+路径
//! 定位进程后 TerminateProcess, 只由人工在页面显式触发 (会丢未落盘数据)。
//!
//! 不做 install-on-missing (start 分支): legacy 在 start 时若服务未装会先 InstallService,
//! Rust 简化为未装直接报错 -> 前端走 /deploy。(U8 后已无反代。)

use std::path::Path;
use std::time::{Duration, Instant};

use crate::win32::proc::ProcessSnapshot;
use windows::core::PCWSTR;
use windows::Win32::Foundation::CloseHandle;
use windows::Win32::System::Services::{
    CloseServiceHandle, ControlService, DeleteService, OpenSCManagerW, OpenServiceW,
    QueryServiceStatus, StartServiceW, SERVICE_CONTROL_STOP, SERVICE_RUNNING, SERVICE_STATUS,
    SERVICE_STOP_PENDING, SERVICE_STOPPED, SC_MANAGER_CONNECT, SERVICE_QUERY_STATUS, SERVICE_START,
    SERVICE_STOP,
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
        if QueryServiceStatus(svc, &mut status).is_ok() {
            if status.dwCurrentState == SERVICE_STOPPED {
                let _ = CloseServiceHandle(svc);
                let _ = CloseServiceHandle(scm);
                return Ok(format!("服务 {display} 已经停止"));
            }
            // 已卡在停止中: 再发 STOP 会被拒, 也不该对外说"停止失败"了事 —— 点明现场。
            if status.dwCurrentState == SERVICE_STOP_PENDING {
                let _ = CloseServiceHandle(svc);
                let _ = CloseServiceHandle(scm);
                return Err(format!(
                    "服务 {display} 正在停止中（上一次停止未完成）, 长时间无进展请用「强制停止」"
                ));
            }
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

/// 强制停止: 先试优雅 (10s), 仍卡着 -> 按 exe 名+路径定位进程 -> TerminateProcess ->
/// 再等 SCM 收敛到 STOPPED (10s)。
///
/// 只有一种场合需要它: 服务卡在 STOP_PENDING (SCM 已拒收停止指令、进程赖着不退), 此时
/// 页面上的「停止」永远报超时。**只由人工在页面显式点「强制停止」触发**, 不在上传/停止
/// 流程里自动调用 —— 强行结束有未落盘数据丢失风险, 必须有人点头。
///
/// 只按解析出的单个 pid 动手, 绝不按 exe 名批量杀 (同名多份会误伤别的服务)。
pub fn force_stop_service(service_name: &str, exe_name: &str, exe_path: &Path) -> Result<String, String> {
    let display = display_name(service_name);
    let wide = wide(service_name);
    unsafe {
        let scm = match OpenSCManagerW(PCWSTR::null(), PCWSTR::null(), SC_MANAGER_CONNECT) {
            Ok(h) => h,
            Err(_) => return Err("打开 SCManager 失败".to_string()),
        };
        let svc = match OpenServiceW(
            scm,
            PCWSTR(wide.as_ptr()),
            SERVICE_STOP | SERVICE_QUERY_STATUS,
        ) {
            Ok(h) => h,
            Err(_) => {
                let _ = CloseServiceHandle(scm);
                return Ok(format!("服务 {display} 不存在，无需停止"));
            }
        };
        // 1. 先优雅停 (能正常退就不动刀)
        let mut status = SERVICE_STATUS::default();
        if QueryServiceStatus(svc, &mut status).is_ok()
            && status.dwCurrentState == SERVICE_STOPPED
        {
            let _ = CloseServiceHandle(svc);
            let _ = CloseServiceHandle(scm);
            return Ok(format!("服务 {display} 已经停止"));
        }
        let _ = ControlService(svc, SERVICE_CONTROL_STOP, &mut status); // 已 pending 会失败, 忽略
        if poll_state(svc, SERVICE_STOPPED.0, Duration::from_secs(10)) {
            let _ = CloseServiceHandle(svc);
            let _ = CloseServiceHandle(scm);
            return Ok(format!("服务 {display} 已停止（优雅退出）"));
        }
        // 2. 卡住 -> 定位进程并强杀
        match ProcessSnapshot::capture().find_pid(exe_name, exe_path) {
            None => {
                let _ = CloseServiceHandle(svc);
                let _ = CloseServiceHandle(scm);
                Err(format!(
                    "服务 {display} 卡在停止中, 但按 {exe_name} 未找到存活进程；请上机核查（进程可能已死而 SCM 未收敛）"
                ))
            }
            Some(pid) => match kill_process(pid) {
                Err(e) => {
                    let _ = CloseServiceHandle(svc);
                    let _ = CloseServiceHandle(scm);
                    Err(format!("服务 {display} 卡在停止中, 结束进程 {pid} 失败: {e}"))
                }
                Ok(()) => {
                    let converged = poll_state(svc, SERVICE_STOPPED.0, Duration::from_secs(10));
                    let _ = CloseServiceHandle(svc);
                    let _ = CloseServiceHandle(scm);
                    if converged {
                        Ok(format!("服务 {display} 已强制结束进程 (PID {pid}) 并转为停止"))
                    } else {
                        Err(format!(
                            "服务 {display} 已结束进程 PID {pid}, 但 SCM 10 秒内未收敛到停止, 请上机核查"
                        ))
                    }
                }
            },
        }
    }
}

/// TerminateProcess(pid): 强杀指定进程 (OpenProcess 提权不足时如实报错)。
unsafe fn kill_process(pid: u32) -> Result<(), String> {
    use windows::Win32::System::Threading::{OpenProcess, TerminateProcess, PROCESS_TERMINATE};
    let handle = OpenProcess(PROCESS_TERMINATE, false, pid)
        .map_err(|e| format!("OpenProcess 失败（权限不足？）: {e}"))?;
    let rc = TerminateProcess(handle, 1);
    let _ = CloseHandle(handle);
    rc.map_err(|e| format!("TerminateProcess 失败: {e}"))
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
