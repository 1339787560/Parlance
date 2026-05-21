use serde_json::{json, Value};
use std::fs;
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::process::Command;

// ── 常量 ──

const ALLOWED_EXTENSIONS: &[&str] = &["md", "py", "json"];
const SKIP_DIRS: &[&str] = &[".git", "QuickStartForRole", "WorkFlow", "common", "shared"];
const MCP_VERSION: &str = "2024-11-05";
const SERVER_NAME: &str = "a2a-file-manager";

// ── 路径工具 ──

fn get_a2a_dir() -> PathBuf {
    // 从 exe 所在目录向上查找，找到含 COMMON.md 的目录即为 A2A 根目录
    let start = std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());

    let mut dir = Some(start.as_path());
    while let Some(d) = dir {
        if d.join("COMMON.md").exists() {
            return d.to_path_buf();
        }
        dir = d.parent();
    }
    // 最后兜底用当前目录
    std::env::current_dir().unwrap_or_default()
}

fn safe_relative_path(base: &Path, path: &str) -> Option<String> {
    if path.is_empty() {
        return Some(String::new());
    }
    let stripped = path.trim_start_matches(|c| c == '/' || c == '\\');
    let full = base.join(stripped);
    // 规范化 base（如果存在）
    let canonical_base = if base.exists() {
        base.canonicalize().unwrap_or_else(|_| base.to_path_buf())
    } else {
        base.to_path_buf()
    };
    // 检查用户请求的路径父目录是否在 base 之内
    let parent = match full.parent() {
        Some(p) => p,
        None => return Some(stripped.to_string()),
    };
    if !parent.exists() {
        // 父目录不存在（可能是全新路径），先检查有没有 ".." 穿越
        let normalized = full
            .components()
            .collect::<PathBuf>();
        let cn = if let Ok(c) = normalized.canonicalize() {
            c
        } else {
            // 路径还不存在，用 parent 做 canonical 近似
            if let Ok(cp) = parent.canonicalize() {
                if cp.starts_with(&canonical_base) || canonical_base.starts_with(&cp) {
                    return Some(stripped.to_string());
                }
            }
            return Some(stripped.to_string());
        };
        if cn.starts_with(&canonical_base) || canonical_base.starts_with(&cn) {
            return Some(stripped.to_string());
        }
        return None;
    }
    match parent.canonicalize() {
        Ok(canonical_full) => {
            if canonical_full.starts_with(&canonical_base) {
                Some(stripped.to_string())
            } else {
                None
            }
        }
        Err(_) => Some(stripped.to_string()),
    }
}

// ── Git 工具 ──

fn ensure_git_initialized(a2a: &Path) {
    let git_dir = a2a.join(".git");
    if !git_dir.exists() {
        let _ = fs::create_dir_all(a2a);
        let _ = Command::new("git").args(["init"]).current_dir(a2a).output();
        let _ = Command::new("git")
            .args(["config", "user.email", "a2a@system"])
            .current_dir(a2a)
            .output();
        let _ = Command::new("git")
            .args(["config", "user.name", "A2A System"])
            .current_dir(a2a)
            .output();
    }
}

fn git_commit(a2a: &Path, file_path: &str, message: &str, is_delete: bool) -> bool {
    ensure_git_initialized(a2a);
    if is_delete {
        let _ = Command::new("git")
            .args(["add", "-A"])
            .current_dir(a2a)
            .output();
    } else {
        let _ = Command::new("git")
            .args(["add", file_path])
            .current_dir(a2a)
            .output();
    }
    Command::new("git")
        .args(["commit", "-m", message])
        .current_dir(a2a)
        .env("LANG", "en_US.UTF-8")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

// ── 目录列表 ──

fn list_directory(a2a: &Path, rel_path: &str) -> Vec<Value> {
    let full = if rel_path.is_empty() {
        a2a.to_path_buf()
    } else {
        a2a.join(rel_path)
    };
    if !full.exists() {
        let _ = fs::create_dir_all(&full);
    }
    let Ok(entries) = fs::read_dir(&full) else {
        return vec![];
    };

    let mut items: Vec<Value> = entries
        .filter_map(|e| e.ok())
        .filter(|e| e.file_name() != ".git")
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            let meta = e.metadata().ok()?;
            let is_dir = meta.is_dir();
            let ext = if is_dir {
                None
            } else {
                Path::new(&name)
                    .extension()
                    .map(|ex| ex.to_string_lossy().to_lowercase())
            };
            if !is_dir {
                let ext_str = ext.as_deref().unwrap_or("");
                if !ALLOWED_EXTENSIONS.contains(&ext_str) {
                    return None;
                }
            }
            let item_path = if rel_path.is_empty() {
                name.clone()
            } else {
                format!("{}/{}", rel_path, name)
            };
            Some(json!({
                "name": name,
                "type": if is_dir { "folder" } else { "file" },
                "extension": ext.map(|e| format!(".{}", e)),
                "path": item_path,
                "size": if is_dir { 0 } else { meta.len() },
            }))
        })
        .collect();

    items.sort_by(|a, b| {
        let a_folder = a["type"] == "folder";
        let b_folder = b["type"] == "folder";
        b_folder
            .cmp(&a_folder)
            .then_with(|| a["name"].as_str().unwrap_or("").cmp(b["name"].as_str().unwrap_or("")))
    });
    items
}

// ── 角色发现 ──

fn discover_roles(a2a: &Path) -> Vec<String> {
    let mut roles: Vec<String> = Vec::new();
    let Ok(entries) = fs::read_dir(a2a) else {
        return roles;
    };
    for e in entries.flatten() {
        let name = e.file_name().to_string_lossy().to_string();
        if SKIP_DIRS.contains(&name.as_str()) || name == ".git" {
            continue;
        }
        if e.path().is_dir() && e.path().join("L0_Index.md").exists() {
            roles.push(name);
        }
    }
    roles.sort();
    roles
}

fn read_file_content(full: &Path) -> Option<String> {
    if !full.exists() || full.is_dir() {
        return None;
    }
    fs::read_to_string(full).ok()
}

// ── MCP 工具处理 ──

fn handle_init(args: &Value) -> Value {
    let a2a = get_a2a_dir();
    let role = args.get("role").and_then(|v| v.as_str()).unwrap_or("");

    let roles = discover_roles(&a2a);

    if role.is_empty() {
        let list: Vec<String> = roles.iter().map(|r| format!("  - {}", r)).collect();
        return json!({
            "content": [{
                "type": "text",
                "text": format!(
                    "可用角色列表:\n{}\n\n请指定 role 参数再次调用 a2a_init 来完成初始化。",
                    list.join("\n")
                )
            }]
        });
    }

    if !roles.contains(&role.to_string()) {
        return json!({
            "content": [{
                "type": "text",
                "text": format!("角色 '{}' 不存在。可用角色: {:?}", role, roles)
            }]
        });
    }

    let common = fs::read_to_string(a2a.join("COMMON.md"))
        .unwrap_or_else(|_| "(COMMON.md 不存在)".into());
    let l0 = fs::read_to_string(a2a.join(role).join("L0_Index.md"))
        .unwrap_or_else(|_| format!("(角色 {} 的 L0_Index.md 不存在)", role));
    let bp = fs::read_to_string(a2a.join("common").join("AI_Tool_BestPractices.md"))
        .unwrap_or_default();

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

    json!({
        "content": [{
            "type": "text",
            "text": sections.join("\n")
        }]
    })
}

fn handle_list(args: &Value) -> Value {
    let a2a = get_a2a_dir();
    let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => {
            return json!({
                "content": [{"type": "text", "text": "路径访问被拒绝"}]
            });
        }
    };

    let items = list_directory(&a2a, &rel);
    let folders: Vec<&str> = items
        .iter()
        .filter(|i| i["type"] == "folder")
        .map(|i| i["name"].as_str().unwrap_or(""))
        .collect();

    let mut lines = Vec::new();
    for i in &items {
        let tag = if i["type"] == "folder" {
            "[DIR]".to_string()
        } else {
            format!("[{}]", i["extension"].as_str().unwrap_or(""))
        };
        let size = i["size"].as_u64().unwrap_or(0);
        let size_str = if i["type"] == "file" {
            format!(" ({}B)", size)
        } else {
            String::new()
        };
        lines.push(format!(
            "{} {}{} → {}",
            tag,
            i["name"].as_str().unwrap_or(""),
            size_str,
            i["path"].as_str().unwrap_or("")
        ));
    }
    let header = format!("路径: {} | 文件夹: {:?}", rel, folders);

    json!({
        "content": [{
            "type": "text",
            "text": format!("{}\n{}", header, lines.join("\n"))
        }]
    })
}

fn handle_get(args: &Value) -> Value {
    let a2a = get_a2a_dir();
    let path = match args.get("path").and_then(|v| v.as_str()) {
        Some(p) if !p.is_empty() => p,
        _ => {
            return json!({
                "content": [{"type": "text", "text": "路径不能为空"}]
            });
        }
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => {
            return json!({
                "content": [{"type": "text", "text": "路径访问被拒绝"}]
            });
        }
    };

    let full = a2a.join(&rel);
    match read_file_content(&full) {
        Some(content) => json!({
            "content": [{"type": "text", "text": content}]
        }),
        None => json!({
            "content": [{"type": "text", "text": "文件不存在或为目录"}]
        }),
    }
}

fn handle_create(args: &Value) -> Value {
    let a2a = get_a2a_dir();
    let path = match args.get("path").and_then(|v| v.as_str()) {
        Some(p) if !p.is_empty() => p,
        _ => {
            return json!({
                "content": [{"type": "text", "text": "路径不能为空"}]
            });
        }
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => {
            return json!({
                "content": [{"type": "text", "text": "路径访问被拒绝"}]
            });
        }
    };

    let content = args.get("content").and_then(|v| v.as_str()).unwrap_or("");
    let desc = args.get("desc").and_then(|v| v.as_str()).unwrap_or("");

    let full = a2a.join(&rel);
    if let Some(parent) = full.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Err(e) = fs::write(&full, content) {
        return json!({
            "content": [{"type": "text", "text": format!("写入失败: {}", e)}]
        });
    }

    let file_name = Path::new(path)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| path.to_string());
    let mut commit_msg = format!("{} changed", file_name);
    if !desc.is_empty() {
        commit_msg.push_str(&format!(" - {}", desc));
    }
    git_commit(&a2a, &rel, &commit_msg, false);

    json!({
        "content": [{
            "type": "text",
            "text": format!("文件创建成功 | git: {}", commit_msg)
        }]
    })
}

fn handle_update(args: &Value) -> Value {
    let a2a = get_a2a_dir();
    let path = match args.get("path").and_then(|v| v.as_str()) {
        Some(p) if !p.is_empty() => p,
        _ => {
            return json!({
                "content": [{"type": "text", "text": "路径不能为空"}]
            });
        }
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => {
            return json!({
                "content": [{"type": "text", "text": "路径访问被拒绝"}]
            });
        }
    };

    let content = match args.get("content").and_then(|v| v.as_str()) {
        Some(c) => c,
        None => {
            return json!({
                "content": [{"type": "text", "text": "内容不能为空"}]
            });
        }
    };
    let desc = args.get("desc").and_then(|v| v.as_str()).unwrap_or("");

    let full = a2a.join(&rel);
    if !full.exists() {
        return json!({
            "content": [{"type": "text", "text": "文件不存在"}]
        });
    }
    if let Err(e) = fs::write(&full, content) {
        return json!({
            "content": [{"type": "text", "text": format!("写入失败: {}", e)}]
        });
    }

    let file_name = Path::new(path)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| path.to_string());
    let mut commit_msg = format!("{} changed", file_name);
    if !desc.is_empty() {
        commit_msg.push_str(&format!(" - {}", desc));
    }
    git_commit(&a2a, &rel, &commit_msg, false);

    json!({
        "content": [{
            "type": "text",
            "text": format!("文件修改成功 | git: {}", commit_msg)
        }]
    })
}

fn handle_delete(args: &Value) -> Value {
    let a2a = get_a2a_dir();
    let path = match args.get("path").and_then(|v| v.as_str()) {
        Some(p) if !p.is_empty() => p,
        _ => {
            return json!({
                "content": [{"type": "text", "text": "路径不能为空"}]
            });
        }
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => {
            return json!({
                "content": [{"type": "text", "text": "路径访问被拒绝"}]
            });
        }
    };
    let desc = args.get("desc").and_then(|v| v.as_str()).unwrap_or("");

    let full = a2a.join(&rel);
    if !full.exists() {
        return json!({
            "content": [{"type": "text", "text": "文件不存在"}]
        });
    }
    if let Err(e) = fs::remove_file(&full) {
        return json!({
            "content": [{"type": "text", "text": format!("删除失败: {}", e)}]
        });
    }

    let file_name = Path::new(path)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| path.to_string());
    let mut commit_msg = format!("{} deleted", file_name);
    if !desc.is_empty() {
        commit_msg.push_str(&format!(" - {}", desc));
    }
    git_commit(&a2a, &rel, &commit_msg, true);

    json!({
        "content": [{
            "type": "text",
            "text": format!("文件删除成功 | git: {}", commit_msg)
        }]
    })
}

fn handle_history(args: &Value) -> Value {
    let a2a = get_a2a_dir();
    let path = match args.get("path").and_then(|v| v.as_str()) {
        Some(p) if !p.is_empty() => p,
        _ => {
            return json!({
                "content": [{"type": "text", "text": "路径不能为空"}]
            });
        }
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => {
            return json!({
                "content": [{"type": "text", "text": "路径访问被拒绝"}]
            });
        }
    };

    let output = Command::new("git")
        .args([
            "log",
            "-10",
            "--oneline",
            "--format=%H|%s|%ai|%an",
            "--",
            &rel,
        ])
        .current_dir(&a2a)
        .output();

    let commits: Vec<String> = match output {
        Ok(o) if o.status.success() => {
            let stdout = String::from_utf8_lossy(&o.stdout);
            stdout
                .lines()
                .filter(|l| !l.is_empty())
                .filter_map(|line| {
                    let parts: Vec<&str> = line.splitn(4, '|').collect();
                    if parts.len() >= 4 {
                        let hash = &parts[0][..7.min(parts[0].len())];
                        Some(format!(
                            "{} {} ({}, {})",
                            hash, parts[1], parts[2], parts[3]
                        ))
                    } else {
                        None
                    }
                })
                .collect()
        }
        _ => vec![],
    };

    if commits.is_empty() {
        return json!({
            "content": [{"type": "text", "text": "无提交历史"}]
        });
    }

    json!({
        "content": [{
            "type": "text",
            "text": format!("最近提交:\n{}", commits.join("\n"))
        }]
    })
}

fn handle_version(args: &Value) -> Value {
    let a2a = get_a2a_dir();
    let path = match args.get("path").and_then(|v| v.as_str()) {
        Some(p) if !p.is_empty() => p,
        _ => {
            return json!({
                "content": [{"type": "text", "text": "路径不能为空"}]
            });
        }
    };
    let hash = match args.get("hash").and_then(|v| v.as_str()) {
        Some(h) if !h.is_empty() => h,
        _ => {
            return json!({
                "content": [{"type": "text", "text": "hash 不能为空"}]
            });
        }
    };
    let rel = match safe_relative_path(&a2a, path) {
        Some(r) => r,
        None => {
            return json!({
                "content": [{"type": "text", "text": "路径访问被拒绝"}]
            });
        }
    };

    ensure_git_initialized(&a2a);

    let show_output = Command::new("git")
        .args(["show", &format!("{}:{}", hash, rel)])
        .current_dir(&a2a)
        .output();

    let content = match show_output {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).to_string(),
        _ => {
            return json!({
                "content": [{"type": "text", "text": "获取版本失败"}]
            });
        }
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
                let h = &parts[0][..7.min(parts[0].len())];
                format!("版本: {} | {} | {}", h, parts[1], parts[2])
            } else {
                String::new()
            }
        }
        _ => String::new(),
    };

    let text = if commit_info.is_empty() {
        content
    } else {
        format!("{}\n\n{}", commit_info, content)
    };

    json!({
        "content": [{"type": "text", "text": text}]
    })
}

// ── 工具定义 ──

fn tool_definitions() -> Vec<Value> {
    vec![
        json!({
            "name": "a2a_init",
            "description": "初始化 A2A 工作区。指定 role 则加载 COMMON.md + 角色L0_Index.md；不指定则返回可用角色列表。首次使用必须调用。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "角色名，如 CP-DEV-xzmp、CPP-GameSVR-DEV-xzmp、Creator-Client-DEV-xzmp、LUA-Client-DEV-xzmp、Service-Svr-Dev。留空返回可用角色列表。"
                    }
                }
            }
        }),
        json!({
            "name": "a2a_list",
            "description": "列出 A2A 目录下的文件和子目录。返回 .md/.py/.json 文件和所有文件夹。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对路径，如 'CP-DEV-xzmp'，留空为根目录"
                    }
                },
                "required": ["path"]
            }
        }),
        json!({
            "name": "a2a_get",
            "description": "读取 A2A 文件内容。返回完整文本。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件相对路径，如 'CP-DEV-xzmp/L0_Index.md'"
                    }
                },
                "required": ["path"]
            }
        }),
        json!({
            "name": "a2a_create",
            "description": "创建 A2A 文件，自动 git commit。自动创建中间目录。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "文件相对路径" },
                    "content": { "type": "string", "description": "文件内容，默认空字符串" },
                    "desc": { "type": "string", "description": "git commit 描述，可选" }
                },
                "required": ["path"]
            }
        }),
        json!({
            "name": "a2a_update",
            "description": "全量覆盖更新 A2A 文件内容，自动 git commit。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "文件相对路径" },
                    "content": { "type": "string", "description": "新文件内容" },
                    "desc": { "type": "string", "description": "git commit 描述，可选" }
                },
                "required": ["path", "content"]
            }
        }),
        json!({
            "name": "a2a_delete",
            "description": "删除 A2A 文件，自动 git commit。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "文件相对路径" },
                    "desc": { "type": "string", "description": "git commit 描述，可选" }
                },
                "required": ["path"]
            }
        }),
        json!({
            "name": "a2a_history",
            "description": "获取 A2A 文件最近 10 条 git commit 历史。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "文件相对路径" }
                },
                "required": ["path"]
            }
        }),
        json!({
            "name": "a2a_version",
            "description": "获取 A2A 文件的历史版本内容（按 git hash）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": { "type": "string", "description": "文件相对路径" },
                    "hash": { "type": "string", "description": "git commit hash（7位短hash或完整hash）" }
                },
                "required": ["path", "hash"]
            }
        }),
    ]
}

fn handle_tool_call(name: &str, args: &Value) -> Value {
    match name {
        "a2a_init" => handle_init(args),
        "a2a_list" => handle_list(args),
        "a2a_get" => handle_get(args),
        "a2a_create" => handle_create(args),
        "a2a_update" => handle_update(args),
        "a2a_delete" => handle_delete(args),
        "a2a_history" => handle_history(args),
        "a2a_version" => handle_version(args),
        _ => json!({
            "content": [{"type": "text", "text": format!("未知工具: {}", name)}]
        }),
    }
}

// ── MCP 协议分发 ──

fn make_response(id: i64, result: Value) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": result
    })
}

fn make_error(id: i64, code: i64, message: &str) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": code,
            "message": message
        }
    })
}

fn handle_request(request: &Value) -> Option<Value> {
    let empty_obj = json!({});
    let id = request.get("id").and_then(|v| v.as_i64());
    let method = request.get("method").and_then(|v| v.as_str()).unwrap_or("");
    let params = request.get("params").unwrap_or(&empty_obj);

    match method {
        "initialize" => {
            // 返回服务器能力
            let response = json!({
                "jsonrpc": "2.0",
                "id": id.unwrap_or(1),
                "result": {
                    "protocolVersion": MCP_VERSION,
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": "0.2.0"
                    }
                }
            });
            Some(response)
        }
        "notifications/initialized" | "notifications/cancelled" => {
            // 通知不需要响应
            None
        }
        "tools/list" => {
            let id = id.unwrap_or(1);
            let result = json!({
                "tools": tool_definitions()
            });
            Some(make_response(id, result))
        }
        "tools/call" => {
            let id = id.unwrap_or(1);
            let tool_name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let arguments = params.get("arguments").unwrap_or(&empty_obj);
            let result = if tool_name.is_empty() {
                // 兼容：直接从 params 取参数（某些客户端的行为）
                let actual_name = request
                    .get("params")
                    .and_then(|p| p.get("name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if actual_name.is_empty() {
                    make_error(id, -32602, "Missing tool name")
                } else {
                    make_response(id, handle_tool_call(actual_name, arguments))
                }
            } else {
                make_response(id, handle_tool_call(tool_name, arguments))
            };
            Some(result)
        }
        _ => {
            let id = id.unwrap_or(1);
            Some(make_error(id, -32601, format!("Method not found: {}", method).as_str()))
        }
    }
}

// ── 主循环 ──

fn main() {
    let stdin = io::stdin();
    let mut line = String::new();

    // stderr 输出日志，避免污染 stdout（MCP 通信通道）
    eprintln!("A2A MCP server starting");

    loop {
        line.clear();
        match stdin.lock().read_line(&mut line) {
            Ok(0) => break,   // EOF
            Ok(_) => {}
            Err(e) => {
                eprintln!("stdin error: {}", e);
                break;
            }
        }

        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let request: Value = match serde_json::from_str(trimmed) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("parse error: {} (line: {})", e, trimmed);
                continue;
            }
        };

        match handle_request(&request) {
            Some(response) => {
                let output = serde_json::to_string(&response).unwrap_or_default();
                let stdout = io::stdout();
                let mut handle = stdout.lock();
                let _ = writeln!(handle, "{}", output);
                let _ = handle.flush();
            }
            None => {
                // 通知类消息不需要响应
            }
        }
    }

    eprintln!("A2A MCP server shutting down");
}
