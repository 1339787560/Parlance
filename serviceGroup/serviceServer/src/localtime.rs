//! 本地时间格式化 —— 无日期库依赖 (Cargo 不引 chrono/time)。
//!
//! 序列 `script.json` 的 `created_at`、做牌场景备份的时间戳都需要本地时间字符串。
//! Windows 走 `GetLocalTime`; 非 Windows 退化为 UTC (Mac 无 serviceServer 二进制,
//! 仅为保编译与单测)。`epoch_utc_*` 是纯函数, 供单测与非 Windows 路径复用。

/// 当前本地时间 `YYYY-MM-DD HH:MM:SS` (对齐 Python `time.strftime` 默认形态)。
#[cfg(windows)]
pub fn now_hms() -> String {
    let st = unsafe { windows::Win32::System::SystemInformation::GetLocalTime() };
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond
    )
}

/// 当前本地时间 `YYYYMMDD_HHMMSS` (对齐 Python `strftime('%Y%m%d_%H%M%S')`)。
#[cfg(windows)]
pub fn now_stamp() -> String {
    let st = unsafe { windows::Win32::System::SystemInformation::GetLocalTime() };
    format!(
        "{:04}{:02}{:02}_{:02}{:02}{:02}",
        st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond
    )
}

/// 非 Windows 退化: UTC (仅保编译与单测)。
#[cfg(not(windows))]
pub fn now_hms() -> String {
    epoch_utc_hms(now_epoch_secs())
}

#[cfg(not(windows))]
pub fn now_stamp() -> String {
    epoch_utc_stamp(now_epoch_secs())
}

#[cfg(not(windows))]
fn now_epoch_secs() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// epoch 秒 -> `YYYY-MM-DD HH:MM:SS` (UTC)。纯函数, 可测。
#[cfg_attr(windows, allow(dead_code))]
pub fn epoch_utc_hms(secs: i64) -> String {
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (y, m, d) = civil_from_days(days);
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        y,
        m,
        d,
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

/// epoch 秒 -> `YYYYMMDD_HHMMSS` (UTC)。纯函数, 可测。
#[cfg_attr(windows, allow(dead_code))]
pub fn epoch_utc_stamp(secs: i64) -> String {
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (y, m, d) = civil_from_days(days);
    format!(
        "{:04}{:02}{:02}_{:02}{:02}{:02}",
        y,
        m,
        d,
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

/// Howard Hinnant civil_from_days: 1970-01-01 起的天数 -> (年, 月, 日)。
#[cfg_attr(windows, allow(dead_code))]
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64; // [0, 146096]
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    (if m <= 2 { y + 1 } else { y }, m as u32, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_epoch_utc_hms_known_values() {
        assert_eq!(epoch_utc_hms(0), "1970-01-01 00:00:00");
        assert_eq!(epoch_utc_hms(946_684_800), "2000-01-01 00:00:00");
        assert_eq!(epoch_utc_hms(1_700_000_000), "2023-11-14 22:13:20");
        // 2026-01-01 00:00:00 UTC (非闰年 2025 全年 365 天)
        assert_eq!(epoch_utc_hms(1_767_225_600), "2026-01-01 00:00:00");
    }

    #[test]
    fn test_epoch_utc_stamp_known_values() {
        assert_eq!(epoch_utc_stamp(0), "19700101_000000");
        assert_eq!(epoch_utc_stamp(1_700_000_000), "20231114_221320");
    }

    #[test]
    fn test_now_shape() {
        let hms = now_hms();
        assert_eq!(hms.len(), 19, "YYYY-MM-DD HH:MM:SS: {hms}");
        assert_eq!(&hms[4..5], "-");
        assert_eq!(&hms[10..11], " ");
        assert_eq!(&hms[13..14], ":");
        let year: i32 = hms[..4].parse().expect("年份应为数字");
        assert!((2015..=2100).contains(&year), "年份应合理, got {year}");

        let stamp = now_stamp();
        assert_eq!(stamp.len(), 15, "YYYYMMDD_HHMMSS: {stamp}");
        assert_eq!(&stamp[8..9], "_");
        assert_eq!(&hms[..4], &stamp[..4], "同一时刻的年份应一致");
    }
}
