//! Win32 进程枚举 + 监听端口查询 (windows crate ToolHelp + IP Helper)。
//!
//! 对应 legacy Service.py get_process_id_by_exe + get_ports_by_pid。
//! 单次 list_status 请求内做一次全进程 snapshot + 一次 IP Helper 调用,
//! 避免 N 服务 N 次 syscall (legacy 即每服务 psutil iter, 已知慢源之一)。
//!
//! IPv4 only 起步 (游戏服务 v4 监听为主); IPv6 待 game 实证后扩。

use std::collections::HashMap;
use std::mem::{size_of, zeroed};
use std::path::Path;

use crate::ports_probe::extract_local_port;
use windows::core::PWSTR;
use windows::Win32::Foundation::{CloseHandle, INVALID_HANDLE_VALUE};
use windows::Win32::NetworkManagement::IpHelper::{
    GetExtendedTcpTable, GetExtendedUdpTable, MIB_TCPTABLE_OWNER_PID, MIB_UDPTABLE_OWNER_PID,
    TCP_TABLE_OWNER_PID_LISTENER, UDP_TABLE_OWNER_PID,
};
use windows::Win32::Networking::WinSock::AF_INET;
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
};

/// 单进程条目: pid + exe 名 (lowercase) + exe 完整路径 (lowercase, 已 normcase)。
#[derive(Debug, Clone)]
struct ProcEntry {
    pid: u32,
    exe_name_lc: String,
    exe_full_lc: String,
}

/// 进程 snapshot: 一次 ToolHelp32 遍历采集的全进程列表 (含完整路径, 供路径校验)。
pub struct ProcessSnapshot {
    entries: Vec<ProcEntry>,
}

impl ProcessSnapshot {
    /// 采集当前全进程 snapshot。OpenProcess/QueryFullProcessImageNameW 失败的进程跳过
    /// (权限不足拿不到路径, 不参与匹配)。
    pub fn capture() -> Self {
        let mut entries = Vec::new();
        unsafe {
            let snap = match CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) {
                Ok(h) if h != INVALID_HANDLE_VALUE => h,
                _ => return Self { entries },
            };
            let mut e: PROCESSENTRY32W = zeroed();
            e.dwSize = size_of::<PROCESSENTRY32W>() as u32;
            if Process32FirstW(snap, &mut e).is_ok() {
                loop {
                    let name = wchar_buf_to_string(&e.szExeFile).to_lowercase();
                    let pid = e.th32ProcessID;
                    let full = full_process_path(pid)
                        .map(|p| normcase(&p))
                        .unwrap_or_default();
                    entries.push(ProcEntry {
                        pid,
                        exe_name_lc: name,
                        exe_full_lc: full,
                    });
                    if Process32NextW(snap, &mut e).is_err() {
                        break;
                    }
                }
            }
            let _ = CloseHandle(snap);
        }
        Self { entries }
    }

    /// 按旧 Service.py get_process_id_by_exe 语义匹配第一个 pid:
    /// 1) exe 名 (lowercase) 与期望 exe 名 (lowercase) 相等
    /// 2) 且 proc 完整路径 (lowercase) 含期望 exe 父目录 (lowercase, normalized)
    /// 名匹配但路径拿不到 (权限不足) 也接受, 与 legacy elif not exe_path 等价。
    pub fn find_pid(&self, exe_name: &str, exe_path: &Path) -> Option<u32> {
        let name_lc = exe_name.to_lowercase();
        let parent_lc = exe_path
            .parent()
            .map(|p| normcase(&p.to_string_lossy()))
            .unwrap_or_default();
        for e in &self.entries {
            if e.exe_name_lc != name_lc {
                continue;
            }
            // 名匹配; 路径拿不到 (权限) 直接接受, 与 legacy elif not exe_path 等价。
            if e.exe_full_lc.is_empty() {
                return Some(e.pid);
            }
            if !parent_lc.is_empty() && e.exe_full_lc.contains(&parent_lc) {
                return Some(e.pid);
            }
        }
        None
    }
}

/// 监听端口表: pid -> sorted dedup 端口列表。一次 IP Helper 调用聚合 TCP LISTEN + UDP。
pub struct ListenPorts {
    by_pid: HashMap<u32, Vec<u16>>,
}

impl ListenPorts {
    pub fn capture() -> Self {
        let mut by_pid: HashMap<u32, Vec<u16>> = HashMap::new();
        // 注意: read_*_table 返 (buf, ptr) — buf 必须在遍历期间保持存活,
        // 否则 ptr 悬空 (踩过: 早期版本返裸 ptr, 函数返回 buf drop -> segfault)。
        unsafe {
            if let Some((buf, table)) = read_tcp_table() {
                let count = (*table).dwNumEntries as usize;
                let rows = (*table).table.as_ptr();
                for i in 0..count {
                    let row = &*rows.add(i);
                    let port = extract_local_port(row.dwLocalPort);
                    if port != 0 {
                        by_pid.entry(row.dwOwningPid).or_default().push(port);
                    }
                }
                drop(buf);
            }
            if let Some((buf, table)) = read_udp_table() {
                let count = (*table).dwNumEntries as usize;
                let rows = (*table).table.as_ptr();
                for i in 0..count {
                    let row = &*rows.add(i);
                    let port = extract_local_port(row.dwLocalPort);
                    if port != 0 {
                        by_pid.entry(row.dwOwningPid).or_default().push(port);
                    }
                }
                drop(buf);
            }
        }
        for ports in by_pid.values_mut() {
            ports.sort_unstable();
            ports.dedup();
        }
        Self { by_pid }
    }

    pub fn for_pid(&self, pid: u32) -> Vec<u16> {
        self.by_pid.get(&pid).cloned().unwrap_or_default()
    }
}

/// dwLocalPort 字段语义 + 端口 CSV 格式 见 crate::ports_probe (跨平台纯函数)。
/// 进程 snapshot 与端口聚合留在本模块 (Win32 unsafe 调用)。

// ---- helpers ----

fn wchar_buf_to_string(buf: &[u16]) -> String {
    let len = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..len])
}

/// 路径大小写 + 分隔符归一: Windows 不区分大小写, `/` 与 `\` 等价。
/// legacy 用 os.path.normpath 比较, 这里统一转 `\` + lowercase 便于 contains。
fn normcase(s: &str) -> String {
    s.replace('/', "\\").to_lowercase()
}

unsafe fn full_process_path(pid: u32) -> Option<String> {
    let proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
    let mut buf = [0u16; 1024];
    let mut len = buf.len() as u32;
    let ok = QueryFullProcessImageNameW(proc, PROCESS_NAME_WIN32, PWSTR(buf.as_mut_ptr()), &mut len);
    let _ = CloseHandle(proc);
    if ok.is_ok() {
        Some(String::from_utf16_lossy(&buf[..len as usize]))
    } else {
        None
    }
}

/// 返 (buf, ptr): buf 持分配, ptr = buf.as_ptr() cast; 调用方须保 buf 存活期间遍历。
unsafe fn read_tcp_table() -> Option<(Vec<u8>, *const MIB_TCPTABLE_OWNER_PID)> {
    let mut size: u32 = 0;
    // 第一遍探测大小 (返 ERROR_INSUFFICIENT_BUFFER, 设 size)
    let _ = GetExtendedTcpTable(
        None,
        &mut size,
        false,
        AF_INET.0 as u32,
        TCP_TABLE_OWNER_PID_LISTENER,
        0,
    );
    if size == 0 {
        return None;
    }
    let mut buf = vec![0u8; size as usize];
    let rc = GetExtendedTcpTable(
        Some(buf.as_mut_ptr() as *mut _),
        &mut size,
        false,
        AF_INET.0 as u32,
        TCP_TABLE_OWNER_PID_LISTENER,
        0,
    );
    if rc != 0 {
        return None;
    }
    let ptr = buf.as_ptr() as *const MIB_TCPTABLE_OWNER_PID;
    Some((buf, ptr))
}

unsafe fn read_udp_table() -> Option<(Vec<u8>, *const MIB_UDPTABLE_OWNER_PID)> {
    let mut size: u32 = 0;
    let _ = GetExtendedUdpTable(
        None,
        &mut size,
        false,
        AF_INET.0 as u32,
        UDP_TABLE_OWNER_PID,
        0,
    );
    if size == 0 {
        return None;
    }
    let mut buf = vec![0u8; size as usize];
    let rc = GetExtendedUdpTable(
        Some(buf.as_mut_ptr() as *mut _),
        &mut size,
        false,
        AF_INET.0 as u32,
        UDP_TABLE_OWNER_PID,
        0,
    );
    if rc != 0 {
        return None;
    }
    let ptr = buf.as_ptr() as *const MIB_UDPTABLE_OWNER_PID;
    Some((buf, ptr))
}

