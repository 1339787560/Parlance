//! 路径越权校验 (修复旧 ServiceRoute.py 的 prefix bug)。
//!
//! 旧实现 `abs_file_path.startswith(valid_path)` 让 `D:/svc/evil`
//! 通过 `D:/svc/ev` 校验, 可访问兄弟目录。本实现按路径分量比较。

use std::path::{Component, Path, PathBuf};

/// 判断 candidate 是否位于 valid 根之下 (含 valid 自身)。
pub fn is_within(candidate: &Path, valid: &Path) -> bool {
    let c = normalize(candidate);
    let v = normalize(valid);
    if c == v {
        return true;
    }
    c.starts_with(&v)
}

/// 判断 candidate 是否位于任一 valid 根之下。
pub fn is_within_any(candidate: &Path, valid: &[PathBuf]) -> bool {
    valid.iter().any(|r| is_within(candidate, r))
}

/// 规范化: 去除冗余 `.` / `..` / 多余分隔符, 统一分量。
fn normalize(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for comp in p.components() {
        match comp {
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    /// is_within 路径越权校验矩阵 — 修旧 ServiceRoute.py 的 startswith prefix bug。
    /// 每条 case 是一个边界, 矩阵整体构成防护的 QA 文档 (类 pytest parametrize)。
    #[rstest]
    #[case::descendant("D:/svc/room/sub/cfg.ini", "D:/svc/room", true)]
    #[case::root_self("D:/svc/room", "D:/svc/room", true)]
    #[case::sibling_prefix_collision("D:/svc/evil/secret.ini", "D:/svc/ev", false)]
    #[case::other_root("D:/other/cfg.ini", "D:/svc/room", false)]
    #[case::dotdot_escape("D:/svc/room/sub/../../evil/x.ini", "D:/svc/room", false)]
    fn test_is_within_boundary_matrix(
        #[case] candidate: &str,
        #[case] valid: &str,
        #[case] expected: bool,
    ) {
        assert_eq!(is_within(Path::new(candidate), Path::new(valid)), expected);
    }

    #[rstest]
    #[case::matches_one_root("D:/svc/b/c.ini", true)]
    #[case::matches_no_root("D:/svc/c/c.ini", false)]
    fn test_is_within_any_checks_all_roots(#[case] candidate: &str, #[case] expected: bool) {
        // Arrange: 两个服务根 a 与 b
        let roots = vec![PathBuf::from("D:/svc/a"), PathBuf::from("D:/svc/b")];
        // Act + Assert
        assert_eq!(is_within_any(&PathBuf::from(candidate), &roots), expected);
    }
}
