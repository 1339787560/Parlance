//! serviceServer (Rust 重写) 入口。
//!
//! 迁入 infoServer/serviceGroup/serviceServer/, 由 infoServer 服务组托管 (:5000)。
//! T1 阶段: path 与 status 拆分的轻量端点 (/api/config/files 零 Win32 syscall)。

mod atomic_write;
mod backup;
mod breadcrumb;
mod config;
mod encoding;
mod error;
mod localtime;
mod op_ip;
mod path_check;
mod path_map;
mod ports_probe;
mod pybridge;
mod pyval;
mod routes;
mod state;
mod status;
mod svc_control;
mod templates;
#[cfg(windows)]
mod win32;

use std::net::SocketAddr;
use std::sync::Arc;

use axum::{routing::get, Router};
// axum post 在路由链处用全路径引用 (避免顶层 import 冲突)
use tracing_subscriber::EnvFilter;

use crate::path_map::PathMap;
use crate::routes::{assets, branches, config_file, config_files, cp_data, fetch, files, makecard, migration, money, pages, recorder, records, script, serverstatus, services, spideorder, static_files, templates as tpl};
use crate::state::AppState;
use crate::status::{default_provider, StatusCache};
use std::time::Duration;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    let config_path = std::env::var("SERVICESVR_CONFIG")
        .unwrap_or_else(|_| "config.json".to_string());

    let path_map = Arc::new(PathMap::new());
    // 启动预热; 失败仅警告 (config 可能稍后到位, 请求时重试)。
    if let Err(e) = path_map.refresh(std::path::Path::new(&config_path)) {
        tracing::warn!("启动预热 config.json 失败 (稍后请求重试): {e}");
    }

    // 发布面 (:5099, 由 L2 run.py 承接) —— 工具自身重启委派给它 (routes/services.rs)。
    let deploy_url = std::env::var("SERVICESVR_DEPLOY_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:5099".to_string());
    let http_client = reqwest::Client::builder()
        .build()
        .unwrap_or_else(|_| reqwest::Client::new());

    // 模板 DB: env SERVICESVR_TEMPLATES_DB 优先, 否则 config 同级 CustomRoute/templates.db
    // (复用 legacy 库, 已有模板不丢)。
    let templates_db = std::env::var("SERVICESVR_TEMPLATES_DB").ok();
    let templates = match templates_db {
        Some(p) => match crate::templates::TemplateStore::open(std::path::Path::new(&p)) {
            Ok(s) => Some(Arc::new(s)),
            Err(e) => {
                tracing::warn!("模板 DB 打开失败 ({p}): {e}; /api/templates/* 将 500");
                None
            }
        },
        None => {
            let cfg = std::path::Path::new(&config_path);
            let p = cfg
                .parent()
                .map(|d| d.join("CustomRoute").join("templates.db"))
                .unwrap_or_else(|| std::path::PathBuf::from("CustomRoute/templates.db"));
            match crate::templates::TemplateStore::open(&p) {
                Ok(s) => Some(Arc::new(s)),
                Err(e) => {
                    tracing::warn!("模板 DB 打开失败 ({}): {e}; /api/templates/* 将 500", p.display());
                    None
                }
            }
        }
    };

    // `/static/*` 静态根 (2026-09-22 从 legacy Flask 收编): 直读 config.json 同级 `src`,
    // 与 assetTool.py 写入抓取产物的 `ROOT/src` 是同一目录 (fetch → 展示闭环不变)。
    // 解析不到 → 该前缀一律 404 (U8 后无反代)。
    let static_root = static_files::resolve_static_root(
        std::path::Path::new(&config_path),
        std::env::var(static_files::ENV_STATIC_DIR).ok().as_deref(),
    );
    match &static_root {
        Some(p) => tracing::info!("/static/* 根目录: {}", p.display()),
        None => tracing::warn!(
            "/static/* 根目录未解析 (config 同级 src 缺失? 可用 {} 覆盖); 该前缀将一律 404",
            static_files::ENV_STATIC_DIR
        ),
    }

    // 操作 IP 记录 (2026-09-24): 机器本地 dotfile, 不进 deploy 包 (详见 op_ip 模块头注)。
    let op_ips = Arc::new(crate::op_ip::OpIpStore::load(crate::op_ip::resolve_path(
        std::path::Path::new(&config_path),
        std::env::var(crate::op_ip::ENV_STATE_FILE).ok().as_deref(),
    )));

    let state = AppState {
        config_path: config_path.into(),
        path_map,
        status_cache: Arc::new(StatusCache::new(Duration::from_secs(10))),
        status_provider: Arc::from(default_provider()),
        deploy_url,
        http_client,
        templates,
        static_root,
        op_ips,
    };

    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/recorder", get(recorder::page))
        .route("/recorder/demo", get(recorder::demo))
        .route("/recorder/mj_color0.png", get(recorder::sprite))
        // 页面壳 + 静态数据 (U4 迁移, 2026-09-22): 模板按运行时路径从 legacy 目录读后发
        // HTML —— 这些模板无 Jinja 语法, 静态发等价 legacy render_template (详见 routes/pages.rs)。
        .route("/", get(pages::index))
        .route("/sequence", get(pages::sequence))
        .route("/deposit", get(pages::deposit))
        .route("/makecard", get(pages::makecard))
        .route("/serverstatus", get(pages::serverstatus))
        .route("/onlineConfigModify", get(pages::online_config_modify))
        .route("/api/friendlinks", get(pages::friendlinks))
        // 补齐 /api/templates 家族最后一条 (get/save/delete 早已原生), 故该前缀已可全收编。
        .route(
            "/api/templates/update",
            axum::routing::post(pages::templates_update),
        )
        // 服务器状态页数据面 + 系统重启 (2026-09-22): 页面壳 U4 已原生 (见上 /serverstatus),
        // 本批补齐它背后的两条。legacy 的 /api/serverstatus/stop 与 /api/serverstatus/restart
        // **不迁** —— 前者停自己会致入口消失 (首刀裁定), 后者等价能力已在 /api/services/restart
        // 的 self 分支; 二者与 legacy 路由一并退役, 详见 routes/serverstatus.rs 头注。
        .route("/api/serverstatus/get", get(serverstatus::get))
        .route(
            "/api/system/restart",
            axum::routing::post(serverstatus::system_restart),
        )
        // 复盘器数据源 (SDD running/四川麻将复盘器-数据源): 三类源统一 /api/record/*
        .route("/api/record/sources", get(records::sources))
        .route("/api/record/list", get(records::list))
        .route("/api/record/get", get(records::get))
        .route("/api/record/scan_rounds", get(records::scan_rounds))
        .route("/api/record/script", get(records::script))
        .route("/api/record/makecards", get(records::makecards))
        .route(
            "/api/record/activate_makecard",
            axum::routing::post(records::activate_makecard),
        )
        .route(
            "/api/record/save_makecard",
            axum::routing::post(records::save_makecard),
        )
        .route(
            "/api/record/delete_makecard",
            axum::routing::post(records::delete_makecard),
        )
        .route("/api/config/files", get(config_files::list_files))
        .route("/api/config", get(config_files::get_config))
        .route("/api/fetch-title", get(fetch::fetch_title))
        // 资源抓取 (U4 收尾 2026-09-22 / 助手二进制化 2026-09-22): 抓取与缓存在助手内部
        // (开发机: assetTool.py 的 requests/bs4/playwright; 部署: 优先冻结产物 assetTool.exe),
        // 前台只做参数校验与响应整形。两件顺带成果: playwright 既离开了**服务启动链**(N9),
        // 也不再是**部署链**依赖 —— exe 内自带, 且浏览器改用系统 chrome/edge (channel)。
        // 注意: 返回的 /static/* 自 2026-09-22 起由**前台原生**提供 (routes/static_files.rs),
        // 该前缀已前台原生收编 (U8 后无反代)。
        .route("/api/fetch-background", get(assets::fetch_background))
        .route("/api/fetch-metadata", get(assets::fetch_metadata))
        // /api/svn/* 已退役 (U5, 2026-09-22 用户裁定): 发布/更新统一走 deploy 产物打包直推,
        // 不再保留 svn 编排 —— 前缀已前台原生; 未匹配子路径一律 404 (U8 后无反代)。
        .route("/api/config/file/content", get(config_file::get_content))
        .route("/api/config/file/download", get(config_file::download_file))
        .route("/api/config/file/save", axum::routing::post(config_file::save_file))
        .route("/api/config/file/branches", get(branches::list_branches))
        .route(
            "/api/config/file/create_branch",
            axum::routing::post(branches::create_branch),
        )
        .route(
            "/api/config/file/switch_branch",
            axum::routing::post(branches::switch_branch),
        )
        .route(
            "/api/config/file/remove_branch",
            axum::routing::delete(branches::remove_branch),
        )
        // 服务目录文件管理 (spec serviceserver_spec/09): 上传 / 删除 / 列备份 / 还原 / 回收站。
        // 五条红线在 files.rs: 只收相对路径、拒 .exe、拒保留区 (.config_history / remove)、
        // 只收文件、分量沙箱。上传走 multipart, 限 200MB (与 download 上限对齐)。
        .route(
            "/api/files/upload",
            axum::routing::post(files::upload_file)
                .layer(axum::extract::DefaultBodyLimit::max(200 * 1024 * 1024)),
        )
        .route("/api/files/delete", axum::routing::post(files::delete_file))
        .route("/api/files/backups", get(files::list_file_backups))
        .route(
            "/api/files/restore",
            axum::routing::post(files::restore_file),
        )
        .route("/api/files/recycle", get(files::list_recycle))
        .route("/api/services/status", get(services::list_status))
        .route("/api/config/services/running", get(services::running_services))
        .route(
            "/api/services/start",
            axum::routing::post(services::start_service),
        )
        .route(
            "/api/services/stop",
            axum::routing::post(services::stop_service),
        )
        // 卡在 pending (停止中) 时的人工兜底: 强杀进程 (会丢未落盘数据, 前端二次确认)。
        .route(
            "/api/services/force-stop",
            axum::routing::post(services::force_stop_service),
        )
        .route(
            "/api/services/restart",
            axum::routing::post(services::restart_service),
        )
        .route(
            "/api/services/delete",
            axum::routing::post(services::delete_service),
        )
        .route("/api/templates/get", get(tpl::get))
        .route("/api/templates/save", axum::routing::post(tpl::save))
        .route("/api/templates/delete", axum::routing::post(tpl::delete))
        // spideorder 簇: config 读写 + 后台执行 spideOnlineLog.py (脚本与 exe 同目录)。
        .route("/api/spideorder/get", get(spideorder::get_config))
        .route("/api/spideorder/save", axum::routing::post(spideorder::save_config))
        .route("/api/spideorder/execute", axum::routing::post(spideorder::execute))
        // 启动序列 (U1 序列迁移, 2026-09-21): script.json 读写 + 按序列启动服务。
        // 对应 legacy CustomRoute/SequenceRoute.py 四路由; 前缀已前台原生 (U8 后无反代),
        // 不再回退 5099。
        .route("/api/script/get-all", get(script::get_all))
        .route("/api/script/save", axum::routing::post(script::save))
        .route(
            "/api/script/execute/:name",
            axum::routing::post(script::execute_named),
        )
        .route("/api/script/execute", axum::routing::post(script::execute))
        // 做牌器 + 发牌配置 (U2 迁移, 2026-09-21): 直读本机服务目录 test*.ini /
        // 写 config.json 的 makedealFilePath。二者均已前台原生 (U8 后无反代)。
        .route("/api/makecard/files", get(makecard::files))
        .route("/api/makecard/read", get(makecard::read))
        .route("/api/makecard/save", axum::routing::post(makecard::save))
        .route("/api/makecard/activate", axum::routing::post(makecard::activate))
        .route("/api/makecard/delete", axum::routing::post(makecard::delete))
        .route("/api/makecard/rename", axum::routing::post(makecard::rename))
        .route("/api/makecard/made", get(makecard::made))
        .route("/api/makecard/toggle", axum::routing::post(makecard::toggle))
        .route(
            "/api/makedeal/start",
            axum::routing::post(makecard::makedeal_start),
        )
        .route("/api/makedeal/randomReject", get(makecard::makedeal_random_reject))
        // 货币与礼包 (U3 迁移, 2026-09-22): 游戏币(起 RobotToolD.exe) / deposit 远程转发 /
        // 游戏库 Lua 数据(经 luaDataTool.py 助手)。前缀已前台原生 (U8 后无反代)。
        .route("/api/set-gold", axum::routing::post(money::set_gold))
        .route("/api/set-points", axum::routing::post(money::set_points))
        .route("/api/set-silver", axum::routing::post(money::set_silver))
        .route("/api/set-tqvip", axum::routing::post(money::set_tqvip))
        .route("/api/set-weekcard", axum::routing::post(money::set_weekcard))
        .route("/api/set-monthcard", axum::routing::post(money::set_monthcard))
        .route("/api/query-costume", axum::routing::post(money::query_costume))
        .route(
            "/api/set-newplayer-gift",
            axum::routing::post(money::set_newplayer_gift),
        )
        // CP 用户数据 (U6 迁移, 2026-09-22): deposit 页「CP 数据」tab 的六条 —— 原 legacy
        // CustomRoute/CpDirectRoute.py。数据层(CredsManager 解密 + CP MySQL modsvr283db +
        // redis db10)留在 Python 助手 cpDataTool.py, 前台只做确定性预检与响应整形
        // (同 U3/U4 的 pybridge 范式)。前缀已前台原生 (U8 后无反代)。
        .route(
            "/api/cp-data/direct/appcodes",
            get(cp_data::appcodes).post(cp_data::appcodes),
        )
        .route(
            "/api/cp-data/direct/modules",
            axum::routing::post(cp_data::modules),
        )
        .route(
            "/api/cp-data/direct/module",
            axum::routing::post(cp_data::module),
        )
        .route(
            "/api/cp-data/direct/write-prepare",
            axum::routing::post(cp_data::write_prepare),
        )
        .route(
            "/api/cp-data/direct/write",
            axum::routing::post(cp_data::write),
        )
        .route(
            "/api/cp-data/direct/clear",
            axum::routing::post(cp_data::clear),
        )
        // 迁移测试面 (U6 迁移, 2026-09-22): deposit 页「获取装载迁移数据」tab 的后端 ——
        // 原 legacy CustomRoute/MigrationRoute.py。纯 HTTP 调本机 chunkSvr 调试口, 故
        // Rust 原生 (无 Python 助手)。前缀已前台原生 (U8 后无反代)。
        .route(
            "/api/migration/dryrun",
            axum::routing::post(migration::dryrun),
        )
        // 迁移测试面 · 构造数据 (2026-09-23): deposit 页「金币」/「装扮」tab 用 —— 走同一条
        // chunkSvr 调试口, 数据层在 Migration.lua (`migrationsetgold` / `migrationsetcostumeexpire`
        // / `migrationdecorationlist`)。用途: 构造「三类玩家」等迁移测试起始态
        // (金币决定 tier1; 有时限装扮决定 tier2)。
        .route(
            "/api/migration/set-gold",
            axum::routing::post(migration::set_gold),
        )
        .route(
            "/api/migration/set-costume-expire",
            axum::routing::post(migration::set_costume_expire),
        )
        .route(
            "/api/migration/decoration-list",
            axum::routing::post(migration::decoration_list),
        )
        // services 控制簇剩余: deploy(sc create) + start-all + update(multipart 热更新)。
        .route("/api/services/deploy", axum::routing::post(services::deploy_service))
        .route("/api/services/start-all", axum::routing::post(services::start_all_services))
        .route(
            "/api/services/update",
            axum::routing::post(services::update_service)
                .layer(axum::extract::DefaultBodyLimit::max(200 * 1024 * 1024)),
        )
        // 静态资源 (2026-09-22 从 legacy 收编): 抓取产物 / 图标 / 背景图 / friendlink.json
        // 直读 config.json 同级 `src` (与 assetTool.py 的 ROOT/src 同一目录)。此前经
        // Flask static 反代提供; 收编后前台原生, 不再有反代。
        .route("/static/*path", get(static_files::serve))
        // U8 收口 (2026-09-22): legacy Flask 的业务路由已全部迁完/退役 (其 url_map 只剩
        // Flask 自带的 /static), 故**删除 strangler 反代 fallback** —— 未匹配请求不再
        // 转发给 :5098, 直接 404。fallback 保留前台统一的 JSON 错误体
        // (`{success:false,message}`), 与退役前死前缀的 404 形态一致 (前端按 JSON 解析)。
        .fallback(|| async { crate::error::AppError::NotFound })
        // 全 HTML 页面 (rust 内嵌，U8 后无反代) 注入面包屑条 (第二层下拉直达切换)
        .layer(axum::middleware::from_fn(crate::breadcrumb::inject))
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 5000));
    tracing::info!("service-server listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    // with_connect_info: 让 handler 能用 ConnectInfo<SocketAddr> 取请求对端 IP
    // (操作 IP 记录用; 见 op_ip::client_ip)。
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await?;
    Ok(())
}
