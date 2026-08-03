//! PortsProbe: ports 字段探测的跨平台封装 + 纯函数辅助。
//!
//! windows: 包装 crate::win32::proc 的 ProcessSnapshot + ListenPorts (一次 snapshot
//!   全进程 + IP Helper LISTEN 聚合), 按 exe+path 查 pid 再取监听端口 CSV。
//! 非 windows: 空 stub (服务管理本身在非 windows 无意义, 仅保编译过)。

#[cfg(windows)]
pub struct PortsProbe {
    snap: crate::win32::proc::ProcessSnapshot,
    ports: crate::win32::proc::ListenPorts,
}

#[cfg(windows)]
impl PortsProbe {
    pub fn capture() -> Self {
        Self {
            snap: crate::win32::proc::ProcessSnapshot::capture(),
            ports: crate::win32::proc::ListenPorts::capture(),
        }
    }

    pub fn find_pid(&self, exe: &str, exe_path: &std::path::Path) -> Option<u32> {
        self.snap.find_pid(exe, exe_path)
    }

    pub fn ports_for_pid(&self, pid: u32) -> Vec<u16> {
        self.ports.for_pid(pid)
    }
}

#[cfg(not(windows))]
pub struct PortsProbe;

#[cfg(not(windows))]
impl PortsProbe {
    pub fn capture() -> Self {
        Self
    }
    pub fn find_pid(&self, _exe: &str, _exe_path: &std::path::Path) -> Option<u32> {
        None
    }
    pub fn ports_for_pid(&self, _pid: u32) -> Vec<u16> {
        Vec::new()
    }
}

/// dwLocalPort 字段语义 (MSDN): 端口以 network byte order 存于低 16 位。
/// 等价 ntohs((u_short)dwLocalPort) = 低 16 位 swap_bytes (小端主机)。
pub fn extract_local_port(dw_local_port: u32) -> u16 {
    let lo = (dw_local_port & 0xFFFF) as u16;
    lo.swap_bytes()
}

/// 端口列表 -> CSV 字符串。空 -> "未监听" (legacy port_str 一致)。
pub fn format_ports_csv(ports: &[u16]) -> String {
    if ports.is_empty() {
        "未监听".to_string()
    } else {
        ports
            .iter()
            .map(|p| p.to_string())
            .collect::<Vec<_>>()
            .join(", ")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    /// dwLocalPort 字段语义: 低 16 位 swap_bytes (= ntohs on little-endian)。
    /// 不绑死经验端口值 (需实机 dwLocalPort raw 才知), 只验字节序契约;
    /// 真值正确性靠 live 验证 (Rust /api/services/status vs legacy ports CSV 对齐)。
    #[test]
    fn test_extract_local_port_byte_swap() {
        assert_eq!(extract_local_port(0x1234), 0x3412);
        assert_eq!(extract_local_port(0xABCD), 0xCDAB);
    }

    /// 端口 0 / 高 16 位被 mask。
    #[test]
    fn test_extract_local_port_zero() {
        assert_eq!(extract_local_port(0), 0);
        assert_eq!(extract_local_port(0xFFFF0000), 0);
    }

    /// format_ports_csv 矩阵: 空/单/多。
    #[rstest]
    #[case(&[], "未监听")]
    #[case(&[80u16], "80")]
    #[case(&[8080, 8081], "8080, 8081")]
    fn test_format_ports_csv(#[case] ports: &[u16], #[case] expected: &str) {
        let v = ports.to_vec();
        assert_eq!(format_ports_csv(&v), expected);
    }
}
