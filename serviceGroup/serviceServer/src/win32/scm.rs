//! Win32 SCM 服务状态查询 (windows crate)。
//!
//! service_id = "{name}_{type}" 即 Windows 注册服务名。走 OpenSCManager -> OpenService
//! -> QueryServiceStatus。NotFound (服务未部署) 与 Stopped (已部署未运行) 分辨清晰。
//!
//! 中间态如实映射 (2026-09-23): START/STOP_PENDING 曾经被折叠成 Stopped, 于是「卡在
//! 停止中、进程还活着」在页面上显示「未运行」—— 谎报现场。现在 pending 各有其名。

use crate::status::{ServiceState, ServiceStatusProvider};
use windows::core::PCWSTR;
use windows::Win32::System::Services::{
    CloseServiceHandle, OpenSCManagerW, OpenServiceW, QueryServiceStatus, SERVICE_CONTINUE_PENDING,
    SERVICE_PAUSED, SERVICE_PAUSE_PENDING, SERVICE_RUNNING, SERVICE_START_PENDING, SERVICE_STATUS,
    SERVICE_STOP_PENDING, SERVICE_STOPPED, SC_MANAGER_CONNECT, SERVICE_QUERY_STATUS,
};

pub struct ScmProvider;

impl ServiceStatusProvider for ScmProvider {
    fn query(&self, service_name: &str) -> ServiceState {
        query_state(service_name)
    }
}

fn query_state(service_name: &str) -> ServiceState {
    let wide: Vec<u16> = service_name
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();
    unsafe {
        let scm = match OpenSCManagerW(
            PCWSTR(std::ptr::null()),
            PCWSTR(std::ptr::null()),
            SC_MANAGER_CONNECT,
        ) {
            Ok(h) => h,
            Err(_) => return ServiceState::QueryFailed,
        };
        let svc = match OpenServiceW(scm, PCWSTR(wide.as_ptr()), SERVICE_QUERY_STATUS) {
            Ok(h) => h,
            Err(_) => {
                let _ = CloseServiceHandle(scm);
                return ServiceState::NotFound;
            }
        };
        let mut status = SERVICE_STATUS::default();
        let res = QueryServiceStatus(svc, &mut status);
        let _ = CloseServiceHandle(svc);
        let _ = CloseServiceHandle(scm);
        match res {
            Ok(()) if status.dwCurrentState == SERVICE_RUNNING => ServiceState::Running,
            Ok(()) if status.dwCurrentState == SERVICE_STOPPED => ServiceState::Stopped,
            Ok(())
                if status.dwCurrentState == SERVICE_START_PENDING
                    || status.dwCurrentState == SERVICE_CONTINUE_PENDING =>
            {
                ServiceState::StartPending
            }
            Ok(()) if status.dwCurrentState == SERVICE_STOP_PENDING => ServiceState::StopPending,
            Ok(())
                if status.dwCurrentState == SERVICE_PAUSED
                    || status.dwCurrentState == SERVICE_PAUSE_PENDING =>
            {
                ServiceState::Paused
            }
            Ok(()) => ServiceState::Stopped,
            Err(_) => ServiceState::QueryFailed,
        }
    }
}
