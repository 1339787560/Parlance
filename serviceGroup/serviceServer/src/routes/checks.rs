//! 配置文件操作前置校验 (路径越权 + 扩展名白名单), 供 config_file 与 branches 复用。

use crate::error::{AppError, Result};
use crate::path_check::{is_within, is_within_any};
use crate::state::AppState;
use std::path::{Path, PathBuf};

const ALLOWED_EXTS: &[&str] = &["ini", "json", "lua"];

/// tool 自身配置文件名 (相对 infoServer 根)。
const TOOL_CONFIG_NAMES: &[&str] = &["config.yaml", "config.full.yaml"];

/// infoServer 仓根: exe 运行位 = <root>/serviceGroup/serviceServer/service-server.exe。
///
/// 用 current_exe 而非 cwd —— 服务可能被任意宿主以不同 cwd 拉起 (config.yaml 的
/// cwd=serviceGroup/serviceServer), 只有 exe 自身位置是稳定的锚。
pub fn info_server_root() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    // service-server.exe → serviceServer → serviceGroup → infoServer
    exe.parent()?.parent()?.parent().map(|p| p.to_path_buf())
}

/// 工具自身配置文件绝对路径 (存在的才返回)。
///
/// 供 service-server 自陈列「修改配置」: 只放行这两份声明本工具自身的配置,
/// 不放宽其它服务的沙箱与扩展名白名单。
pub fn tool_config_files() -> Vec<PathBuf> {
    let Some(root) = info_server_root() else {
        return Vec::new();
    };
    TOOL_CONFIG_NAMES
        .iter()
        .map(|n| root.join(n))
        .filter(|p| p.is_file())
        .collect()
}

/// 该路径是否属于工具自身配置文件白名单 (精确路径匹配)。
pub fn is_tool_config(target: &Path) -> bool {
    tool_config_files().iter().any(|c| is_within(target, c))
}

pub fn assert_within_roots(state: &AppState, target: &Path) -> Result<()> {
    // 工具自身配置是显式白名单 (两文件绝对路径精确匹配), 其余仍走服务根沙箱。
    if is_tool_config(target) {
        return Ok(());
    }
    let roots = state.path_map.valid_roots();
    if is_within_any(target, &roots) {
        Ok(())
    } else {
        Err(AppError::Forbidden)
    }
}

pub fn assert_allowed_ext(path: &Path) -> Result<()> {
    // 工具自身配置是 .yaml —— ini/json/lua 白名单之外的唯一例外, 仅对这两个路径开。
    if is_tool_config(path) {
        return Ok(());
    }
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();
    if ALLOWED_EXTS.iter().any(|a| *a == ext) {
        Ok(())
    } else {
        Err(AppError::InvalidExtension)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// infoServer 根推导: exe 在 <root>/serviceGroup/serviceServer/ 下。
    #[test]
    fn test_info_server_root_from_exe_path() {
        // Arrange: 模拟 exe 路径三层
        let exe = PathBuf::from("D:/infoServer/serviceGroup/serviceServer/service-server.exe");

        // Act
        let root = exe
            .parent()
            .and_then(|p| p.parent())
            .and_then(|p| p.parent())
            .map(|p| p.to_path_buf());

        // Assert
        assert_eq!(root, Some(PathBuf::from("D:/infoServer")));
    }

    /// 白名单只认这两份文件, 同目录兄弟文件不得借道 (分量比较, 非 startswith)。
    #[test]
    fn test_is_tool_config_rejects_sibling_prefix() {
        // Arrange: 伪造白名单判定 (不依赖真实 infoServer 布局)
        let allow = PathBuf::from("D:/infoServer/config.yaml");

        // Act + Assert: 精确命中放行, 前缀相同的兄弟文件与越权路径拒绝
        assert!(is_within(&allow, &allow));
        assert!(!is_within(
            Path::new("D:/infoServer/config.yaml.bak"),
            &allow
        ));
        assert!(!is_within(Path::new("D:/infoServer/serviceGroup/x.json"), &allow));
    }

    /// 扩展名白名单: 普通服务路径仍不允许 .yaml (工具配置是唯一例外)。
    #[test]
    fn test_allowed_ext_still_rejects_yaml_for_plain_paths() {
        // Act + Assert: 非工具配置的 yaml 不在 ini/json/lua 白名单内
        let plain = Path::new("D:/game/zgda/server_assist/app.yaml");
        let ext = plain.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
        assert!(!ALLOWED_EXTS.iter().any(|a| *a == ext));
    }
}
