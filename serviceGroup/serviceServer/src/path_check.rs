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

    #[test]
    fn rejects_sibling_prefix_collision() {
        // 旧 bug 场景: startswith 让 evil 通过。
        let valid = Path::new("D:/svc/ev");
        let candidate = Path::new("D:/svc/evil/secret.ini");
        assert!(!is_within(candidate, valid));
    }

    #[test]
    fn allows_descendant() {
        let valid = Path::new("D:/svc/room");
        let candidate = Path::new("D:/svc/room/sub/cfg.ini");
        assert!(is_within(candidate, valid));
    }

    #[test]
    fn allows_root_self() {
        let valid = Path::new("D:/svc/room");
        assert!(is_within(valid, valid));
    }

    #[test]
    fn rejects_other_root() {
        let valid = Path::new("D:/svc/room");
        let candidate = Path::new("D:/other/cfg.ini");
        assert!(!is_within(candidate, valid));
    }

    #[test]
    fn normalizes_dotdot_escape() {
        let valid = Path::new("D:/svc/room");
        let candidate = Path::new("D:/svc/room/sub/../../evil/x.ini");
        assert!(!is_within(candidate, valid));
    }

    #[test]
    fn within_any_matches_one_root() {
        let roots = vec![PathBuf::from("D:/svc/a"), PathBuf::from("D:/svc/b")];
        assert!(is_within_any(&PathBuf::from("D:/svc/b/c.ini"), &roots));
        assert!(!is_within_any(&PathBuf::from("D:/svc/c/c.ini"), &roots));
    }
}
