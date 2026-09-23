//! ServiceControl: SCM 控制的跨平台封装。
//!
//! windows: 转发 crate::win32::control 的 start/stop/delete。
//! 非 windows: stub (服务管理本身在非 windows 无意义)。

#[cfg(windows)]
pub mod imp {
    use crate::win32::control;

    pub fn start(name: &str) -> Result<String, String> {
        control::start_service(name)
    }
    pub fn stop(name: &str) -> Result<String, String> {
        control::stop_service(name)
    }
    /// 强制停止 (卡在 pending 时的兜底): 只由人工显式触发, 见 control::force_stop_service。
    pub fn force_stop(
        name: &str,
        exe_name: &str,
        exe_path: &std::path::Path,
    ) -> Result<String, String> {
        control::force_stop_service(name, exe_name, exe_path)
    }
    pub fn delete(name: &str) -> Result<String, String> {
        control::delete_service(name)
    }
}

#[cfg(not(windows))]
pub mod imp {
    pub fn start(_name: &str) -> Result<String, String> {
        Err("non-windows stub".into())
    }
    pub fn stop(_name: &str) -> Result<String, String> {
        Err("non-windows stub".into())
    }
    pub fn force_stop(
        _name: &str,
        _exe_name: &str,
        _exe_path: &std::path::Path,
    ) -> Result<String, String> {
        Err("non-windows stub".into())
    }
    pub fn delete(_name: &str) -> Result<String, String> {
        Err("non-windows stub".into())
    }
}
