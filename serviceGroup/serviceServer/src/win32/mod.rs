//! Win32 平台特定实现 (cfg(windows))。非 windows 平台此 mod 为空。

#[cfg(windows)]
pub mod control;
#[cfg(windows)]
pub mod proc;
#[cfg(windows)]
pub mod scm;
