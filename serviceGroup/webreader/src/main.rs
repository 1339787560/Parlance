//! WebReader 独立服务入口。
//!
//! 由 infoserver 作为子服务托管，独立于 RoleManager。
//! 配置: 第一个 CLI 参数 > $WEBREADER_CONFIG > ./config.json

mod config;
mod git_util;
mod http_reader;
mod paths;

fn main() {
    let config_path = std::env::args()
        .nth(1)
        .or_else(|| std::env::var("WEBREADER_CONFIG").ok())
        .unwrap_or_else(|| "config.json".to_string());

    let path = std::path::PathBuf::from(config_path);
    if let Err(e) = config::init(&path) {
        eprintln!("[webreader] config error: {}", e);
        std::process::exit(1);
    }

    eprintln!(
        "[webreader] workspace={} static={} port={}",
        config::config().workspace.display(),
        config::config().static_dir.display(),
        config::config().port
    );

    http_reader::run();
}
