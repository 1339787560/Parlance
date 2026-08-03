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
    pub fn delete(_name: &str) -> Result<String, String> {
        Err("non-windows stub".into())
    }
}
