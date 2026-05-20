use actix_cors::Cors;
use actix_web::{web, App, HttpServer, HttpResponse};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const ALLOWED_EXTENSIONS: &[&str] = &["md", "py", "json"];
const SKIP_DIRS: &[&str] = &[".git", "QuickStartForRole", "WorkFlow", "common", "shared"];

fn a2a_dir_from_exe() -> PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());
    exe_dir.join("src").join("roleManager")
}

fn a2a_dir_from_cwd() -> PathBuf {
    let cwd = std::env::current_dir().unwrap_or_default();
    if cwd.file_name().map(|n| n == "roleManager").unwrap_or(false) {
        cwd.clone()
    } else {
        cwd.join("src").join("roleManager")
    }
}

fn get_a2a_dir() -> PathBuf {
    let d = a2a_dir_from_exe();
    if d.exists() { return d; }
    let d2 = a2a_dir_from_cwd();
    if d2.exists() { return d2; }
    d
}

fn safe_relative_path(base: &Path, path: &str) -> Option<String> {
    if path.is_empty() { return Some(String::new()); }
    let stripped = path.trim_start_matches(|c| c == '/' || c == '\\');
    let full = base.join(stripped);
    let canonical_base = if base.exists() {
        base.canonicalize().unwrap_or_else(|_| base.to_path_buf())
    } else {
        base.to_path_buf()
    };
    let parent = match full.parent() {
        Some(p) => p,
        None => return Some(stripped.to_string()),
    };
    if !parent.exists() { return Some(stripped.to_string()); }
    match parent.canonicalize() {
        Ok(canonical_full) if canonical_full.starts_with(&canonical_base) || canonical_base.starts_with(&canonical_full) => {
            Some(stripped.to_string())
        }
        Ok(_) => None,
        Err(_) => Some(stripped.to_string()),
    }
}

fn ensure_git_initialized(a2a: &Path) {
    let git_dir = a2a.join(".git");
    if !git_dir.exists() {
        let _ = fs::create_dir_all(a2a);
        let _ = Command::new("git").args(["init"]).current_dir(a2a).output();
        let _ = Command::new("git").args(["config", "user.email", "a2a@system"]).current_dir(a2a).output();
        let _ = Command::new("git").args(["config", "user.name", "A2A System"]).current_dir(a2a).output();
    }
}

fn git_commit(a2a: &Path, file_path: &str, message: &str, is_delete: bool) -> bool {
    ensure_git_initialized(a2a);
    if is_delete {
        let _ = Command::new("git").args(["add", "-A"]).current_dir(a2a).output();
    } else {
        let _ = Command::new("git").args(["add", file_path]).current_dir(a2a).output();
    }
    let output = Command::new("git")
        .args(["commit", "-m", message])
        .current_dir(a2a)
        .env("LANG", "en_US.UTF-8")
        .output();
    match output {
        Ok(o) => o.status.success(),
        Err(_) => false,
    }
}

#[derive(Serialize)]
struct FileItem {
    name: String,
    #[serde(rename = "type")]
    item_type: String,
    extension: Option<String>,
    path: String,
    size: u64,
}

fn list_directory(a2a: &Path, rel_path: &str) -> Vec<FileItem> {
    let full = if rel_path.is_empty() { a2a.to_path_buf() } else { a2a.join(rel_path) };
    if !full.exists() {
        let _ = fs::create_dir_all(&full);
    }
    let Ok(entries) = fs::read_dir(&full) else { return vec![] };

    let mut items: Vec<FileItem> = entries
        .filter_map(|e| e.ok())
        .filter(|e| e.file_name() != ".git")
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            let meta = e.metadata().ok()?;
            let is_dir = meta.is_dir();
            let ext_str = if is_dir {
                None
            } else {
                Path::new(&name).extension().map(|ex| ex.to_string_lossy().to_lowercase())
            };
            if !is_dir {
                let ext_lower = ext_str.as_deref().unwrap_or("");
                if !ALLOWED_EXTENSIONS.contains(&ext_lower) {
                    return None;
                }
            }
            let item_path = if rel_path.is_empty() {
                name.clone()
            } else {
                format!("{}/{}", rel_path, name)
            };
            Some(FileItem {
                name,
                item_type: if is_dir { "folder".into() } else { "file".into() },
                extension: if is_dir { None } else { ext_str.map(|e| format!(".{}", e)) },
                path: item_path,
                size: if is_dir { 0 } else { meta.len() },
            })
        })
        .collect();

    items.sort_by(|a, b| {
        let a_folder = a.item_type == "folder";
        let b_folder = b.item_type == "folder";
        b_folder.cmp(&a_folder).then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
    });
    items
}

// ── Request structs ──

#[derive(Deserialize)]
struct PathQuery {
    path: Option<String>,
}

#[derive(Deserialize)]
struct PathHashQuery {
    path: Option<String>,
    hash: Option<String>,
}

#[derive(Deserialize)]
struct CreateUpdateRequest {
    path: String,
    content: Option<String>,
    desc: Option<String>,
}

#[derive(Deserialize)]
struct DeleteRequest {
    path: String,
    desc: Option<String>,
}

#[derive(Deserialize)]
struct InitQuery {
    role: Option<String>,
}

// ── Handlers ──

async fn api_init(query: web::Query<InitQuery>) -> HttpResponse {
    let a2a = get_a2a_dir();
    let role = query.role.as_deref().unwrap_or("");

    let mut role_dirs: Vec<String> = Vec::new();
    if let Ok(entries) = fs::read_dir(&a2a) {
        for e in entries.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            if SKIP_DIRS.contains(&name.as_str()) || name == ".git" { continue; }
            if e.path().is_dir() && e.path().join("L0_Index.md").exists() {
                role_dirs.push(name);
            }
        }
    }
    role_dirs.sort();

    if role.is_empty() {
        let list = role_dirs.iter().map(|r| format!("  - {}", r)).collect::<Vec<_>>().join("\n");
        return HttpResponse::Ok().json(serde_json::json!({
            "success": true,
            "message": format!("可用角色列表:\n{}\n\n请指定 role 参数再次调用 a2a_init 来完成初始化。", list)
        }));
    }

    if !role_dirs.contains(&role.to_string()) {
        return HttpResponse::Ok().json(serde_json::json!({
            "success": false,
            "message": format!("角色 '{}' 不存在。可用角色: {:?}", role, role_dirs)
        }));
    }

    let common = fs::read_to_string(a2a.join("COMMON.md")).unwrap_or_else(|_| "(COMMON.md 不存在)".into());
    let l0 = fs::read_to_string(a2a.join(role).join("L0_Index.md"))
        .unwrap_or_else(|_| format!("(角色 {} 的 L0_Index.md 不存在)", role));
    let bp = fs::read_to_string(a2a.join("common").join("AI_Tool_BestPractices.md")).unwrap_or_default();

    let mut sections = vec![
        format!("# 工作区已初始化 — 角色: {}", role),
        String::new(),
        "## COMMON.md".into(),
        common,
        String::new(),
        format!("## {}/L0_Index.md", role),
        l0,
    ];
    if !bp.is_empty() {
        sections.push(String::new());
        sections.push("## AI_Tool_BestPractices.md".into());
        sections.push(bp);
    }
    sections.push(String::new());
    sections.push("---".into());
    sections.push("后续操作使用 a2a_list / a2a_get / a2a_create / a2a_update / a2a_delete 等工具。".into());
    sections.push("Cache miss 时主动用 a2a_update 更新笔记。".into());

    HttpResponse::Ok().json(serde_json::json!({
        "success": true,
        "content": sections.join("\n")
    }))
}

async fn api_list(query: web::Query<PathQuery>) -> HttpResponse {
    let a2a = get_a2a_dir();
    let path = query.path.as_deref().unwrap_or("");
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径访问被拒绝"})),
    };

    let items = list_directory(&a2a, &rel);
    let folders: Vec<&str> = items.iter().filter(|i| i.item_type == "folder").map(|i| i.name.as_str()).collect();

    HttpResponse::Ok().json(serde_json::json!({
        "success": true,
        "files": items,
        "current_path": rel,
        "folders": folders
    }))
}

async fn api_get(query: web::Query<PathQuery>) -> HttpResponse {
    let a2a = get_a2a_dir();
    let path = match query.path.as_deref() {
        Some(p) if !p.is_empty() => p,
        _ => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径不能为空"})),
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径访问被拒绝"})),
    };
    let full = a2a.join(&rel);
    if !full.exists() { return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "文件不存在"})); }
    if full.is_dir() { return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "不能读取目录"})); }

    match fs::read_to_string(&full) {
        Ok(content) => {
            let ext = Path::new(path).extension()
                .map(|e| format!(".{}", e.to_string_lossy()))
                .unwrap_or_default();
            let size = fs::metadata(&full).map(|m| m.len()).unwrap_or(0);
            HttpResponse::Ok().json(serde_json::json!({
                "success": true,
                "content": content,
                "extension": ext,
                "size": size
            }))
        }
        Err(e) => HttpResponse::Ok().json(serde_json::json!({"success": false, "message": format!("读取失败: {}", e)})),
    }
}

async fn api_create(body: web::Json<CreateUpdateRequest>) -> HttpResponse {
    let a2a = get_a2a_dir();
    let rel = match safe_relative_path(&a2a, &body.path) {
        Some(r) => r,
        None => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径访问被拒绝"})),
    };
    let full = a2a.join(&rel);
    if let Some(parent) = full.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let content = body.content.as_deref().unwrap_or("");
    if let Err(e) = fs::write(&full, content) {
        return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": format!("写入失败: {}", e)}));
    }

    let file_name = Path::new(&body.path).file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| body.path.clone());
    let mut commit_msg = format!("{} changed", file_name);
    if let Some(desc) = &body.desc {
        if !desc.is_empty() { commit_msg.push_str(&format!(" - {}", desc)); }
    }
    git_commit(&a2a, &rel, &commit_msg, false);

    HttpResponse::Ok().json(serde_json::json!({
        "success": true,
        "message": "文件创建成功",
        "git_commit": commit_msg
    }))
}

async fn api_update(body: web::Json<CreateUpdateRequest>) -> HttpResponse {
    let a2a = get_a2a_dir();
    let rel = match safe_relative_path(&a2a, &body.path) {
        Some(r) => r,
        None => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径访问被拒绝"})),
    };
    let full = a2a.join(&rel);
    if !full.exists() { return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "文件不存在"})); }

    let content = match &body.content {
        Some(c) => c.as_str(),
        None => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "内容不能为空"})),
    };
    if let Err(e) = fs::write(&full, content) {
        return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": format!("写入失败: {}", e)}));
    }

    let file_name = Path::new(&body.path).file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| body.path.clone());
    let mut commit_msg = format!("{} changed", file_name);
    if let Some(desc) = &body.desc {
        if !desc.is_empty() { commit_msg.push_str(&format!(" - {}", desc)); }
    }
    git_commit(&a2a, &rel, &commit_msg, false);

    HttpResponse::Ok().json(serde_json::json!({
        "success": true,
        "message": "文件修改成功",
        "git_commit": commit_msg
    }))
}

async fn api_delete(body: web::Json<DeleteRequest>) -> HttpResponse {
    let a2a = get_a2a_dir();
    let rel = match safe_relative_path(&a2a, &body.path) {
        Some(r) => r,
        None => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径访问被拒绝"})),
    };
    let full = a2a.join(&rel);
    if !full.exists() { return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "文件不存在"})); }

    if let Err(e) = fs::remove_file(&full) {
        return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": format!("删除失败: {}", e)}));
    }

    let file_name = Path::new(&body.path).file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| body.path.clone());
    let mut commit_msg = format!("{} deleted", file_name);
    if let Some(desc) = &body.desc {
        if !desc.is_empty() { commit_msg.push_str(&format!(" - {}", desc)); }
    }
    git_commit(&a2a, &rel, &commit_msg, true);

    HttpResponse::Ok().json(serde_json::json!({
        "success": true,
        "message": "文件删除成功",
        "git_commit": commit_msg
    }))
}

#[derive(Serialize)]
struct CommitEntry {
    hash: String,
    message: String,
    date: String,
    author: String,
}

async fn api_history(query: web::Query<PathQuery>) -> HttpResponse {
    let a2a = get_a2a_dir();
    let path = match query.path.as_deref() {
        Some(p) if !p.is_empty() => p,
        _ => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径不能为空"})),
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径访问被拒绝"})),
    };

    let output = Command::new("git")
        .args(["log", "-10", "--oneline", "--format=%H|%s|%ai|%an", "--", &rel])
        .current_dir(&a2a)
        .output();

    let commits = match output {
        Ok(o) if o.status.success() => {
            let stdout = String::from_utf8_lossy(&o.stdout);
            stdout.lines()
                .filter(|l| !l.is_empty())
                .filter_map(|line| {
                    let parts: Vec<&str> = line.splitn(4, '|').collect();
                    if parts.len() >= 4 {
                        Some(CommitEntry {
                            hash: parts[0][..7.min(parts[0].len())].to_string(),
                            message: parts[1].to_string(),
                            date: parts[2].to_string(),
                            author: parts[3].to_string(),
                        })
                    } else { None }
                })
                .collect::<Vec<_>>()
        }
        _ => vec![],
    };

    HttpResponse::Ok().json(serde_json::json!({
        "success": true,
        "commits": commits
    }))
}

async fn api_version(query: web::Query<PathHashQuery>) -> HttpResponse {
    let a2a = get_a2a_dir();
    let path = match query.path.as_deref() {
        Some(p) if !p.is_empty() => p,
        _ => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径不能为空"})),
    };
    let hash = match query.hash.as_deref() {
        Some(h) if !h.is_empty() => h,
        _ => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "hash不能为空"})),
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "路径访问被拒绝"})),
    };
    ensure_git_initialized(&a2a);

    let show_output = Command::new("git")
        .args(["show", &format!("{}:{}", hash, rel)])
        .current_dir(&a2a)
        .output();

    let content = match show_output {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).to_string(),
        _ => return HttpResponse::Ok().json(serde_json::json!({"success": false, "message": "获取版本失败"})),
    };

    let log_output = Command::new("git")
        .args(["log", "-1", "--format=%H|%s|%ai", hash])
        .current_dir(&a2a)
        .output();

    let commit_info = match log_output {
        Ok(o) if o.status.success() => {
            let stdout = String::from_utf8_lossy(&o.stdout);
            let parts: Vec<&str> = stdout.trim().splitn(3, '|').collect();
            if parts.len() >= 3 {
                serde_json::json!({
                    "hash": parts[0][..7.min(parts[0].len())].to_string(),
                    "message": parts[1],
                    "date": parts[2]
                })
            } else {
                serde_json::json!({})
            }
        }
        _ => serde_json::json!({}),
    };

    HttpResponse::Ok().json(serde_json::json!({
        "success": true,
        "content": content,
        "commit": commit_info
    }))
}

async fn api_health() -> HttpResponse {
    HttpResponse::Ok().json(serde_json::json!({
        "success": true,
        "service": "RoleManager",
        "version": "0.1.0"
    }))
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    let port: u16 = std::env::var("ROLE_MANAGER_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(5080);

    println!("RoleManager starting on 0.0.0.0:{}", port);
    println!("A2A dir: {:?}", get_a2a_dir());

    HttpServer::new(|| {
        let cors = Cors::default()
            .allow_any_origin()
            .allow_any_method()
            .allow_any_header()
            .max_age(3600);

        App::new()
            .wrap(cors)
            .route("/api/a2a/health", web::get().to(api_health))
            .route("/api/a2a/init", web::get().to(api_init))
            .route("/api/a2a/list", web::get().to(api_list))
            .route("/api/a2a/get", web::get().to(api_get))
            .route("/api/a2a/create", web::post().to(api_create))
            .route("/api/a2a/update", web::post().to(api_update))
            .route("/api/a2a/delete", web::post().to(api_delete))
            .route("/api/a2a/history", web::get().to(api_history))
            .route("/api/a2a/version", web::get().to(api_version))
    })
    .bind(("0.0.0.0", port))?
    .run()
    .await
}
