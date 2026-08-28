//! Web Reader HTTP 服务 (独立子服务): 浏览器阅读 + 编辑工作区文档。
//! 由 infoserver 托管, 不再依赖 RoleManager。配置见 config.rs。

use crate::config::config;
use crate::git_util::{file_history, file_version, file_is_dirty, git_commit};
use crate::paths::{apply_role_prefix, discover_roles, safe_relative_path};
use serde_json::{json, Value};
use std::fs;
use std::io::{BufRead, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::io::Cursor;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use base64::Engine;
use rayon::prelude::*;
use sha1::{Digest, Sha1};

const HTTP_MAX_BODY: usize = 8 * 1024 * 1024; // 8MB
const COLLECT_CACHE_TTL: Duration = Duration::from_secs(5);
const SEARCH_INDEX_TTL: Duration = Duration::from_secs(5);
const SEARCH_MAX_RESULTS: usize = 500;
const SEARCH_BINARY_EXTS: &[&str] = &[
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "pdf", "zip", "gz", "tar",
    "7z", "rar", "exe", "dll", "so", "dylib", "bin", "dat", "db", "sqlite", "class",
    "jar", "wasm", "mp3", "mp4", "avi", "mov", "mkv", "woff", "woff2", "ttf", "otf", "eot",
];

/// 递归文件列表短期缓存：避免重复全仓扫描。
/// 写操作会调用 invalidate_collect_cache() 即时失效；外部变更由 TTL 兜底。
static COLLECT_CACHE: Mutex<Option<(Instant, Vec<Value>)>> = Mutex::new(None);

pub fn invalidate_collect_cache() {
    if let Ok(mut cache) = COLLECT_CACHE.lock() {
        *cache = None;
    }
}

/// 搜索内容索引：预读文本文件行，避免每次搜索全量读盘。
/// 与文件列表缓存共用 TTL/失效策略；仅索引未超过大小阈值的文本类文件。
#[derive(Clone)]
struct SearchFile {
    rel: String,
    ext: String,
    lines: Vec<String>,
}

#[derive(Clone)]
struct SearchIndex {
    files: Vec<SearchFile>,
}

static SEARCH_INDEX: Mutex<Option<(Instant, SearchIndex)>> = Mutex::new(None);

pub fn invalidate_search_cache() {
    if let Ok(mut cache) = SEARCH_INDEX.lock() {
        *cache = None;
    }
}

pub fn invalidate_caches() {
    invalidate_collect_cache();
    invalidate_search_cache();
}



/// 相对路径解析: safe_relative_path 沙箱 + 透明 roles/ 前缀。
fn resolve_rel(role: &Path, p: &str) -> Option<String> {
    safe_relative_path(role, p).map(|r| apply_role_prefix(&r, &discover_roles(role)))
}

/// 统一隐藏判定：配置的隐藏文件夹/文件 + dotfile 默认隐藏 + 隐藏正则。
/// rel_path 为斜杠归一后的工作区相对路径；name 为当前条目名。
fn is_hidden_entry(rel_path: &str, name: &str, is_dir: bool) -> bool {
    let cfg = config();
    if is_dir && cfg.hidden_folders.contains(name) {
        return true;
    }
    if !is_dir && cfg.hidden_files.contains(name) {
        return true;
    }
    if name.starts_with('.') && !cfg.visible_dot_dirs.contains(name) {
        return true;
    }
    let rel = rel_path.replace('\\', "/");
    cfg.hidden_patterns
        .iter()
        .any(|re| re.is_match(&rel) || re.is_match(name))
}

// ── 编码与语言映射 ──

fn language_from_ext(ext: &str) -> &'static str {
    match ext.to_lowercase().as_str() {
        "md" | "markdown" => "markdown",
        "py" => "python",
        "rs" => "rust",
        "js" | "mjs" => "javascript",
        "ts" => "typescript",
        "tsx" => "tsx",
        "jsx" => "jsx",
        "json" => "json",
        "html" | "htm" => "xml",
        "css" => "css",
        "cpp" | "cc" | "cxx" | "c" => "cpp",
        "h" | "hpp" | "hh" => "cpp",
        "lua" => "lua",
        "sh" | "bash" | "zsh" => "bash",
        "bat" | "ps1" => "powershell",
        "sql" => "sql",
        "go" => "go",
        "java" => "java",
        "rb" => "ruby",
        "php" => "php",
        _ => "",
    }
}

/// 多编码读取: BOM -> utf-8 -> gbk -> latin-1
fn detect_and_read(path: &Path) -> (String, &'static str) {
    let Ok(bytes) = fs::read(path) else {
        return (String::new(), "utf-8");
    };
    if bytes.len() >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF {
        return (String::from_utf8_lossy(&bytes[3..]).into_owned(), "utf-8-bom");
    }
    if bytes.len() >= 2 {
        if bytes[0] == 0xFF && bytes[1] == 0xFE {
            let units: Vec<u16> = bytes[2..]
                .chunks_exact(2)
                .map(|c| u16::from_le_bytes([c[0], c[1]]))
                .collect();
            return (String::from_utf16_lossy(&units), "utf-16le");
        }
        if bytes[0] == 0xFE && bytes[1] == 0xFF {
            let units: Vec<u16> = bytes[2..]
                .chunks_exact(2)
                .map(|c| u16::from_be_bytes([c[0], c[1]]))
                .collect();
            return (String::from_utf16_lossy(&units), "utf-16be");
        }
    }
    if let Ok(s) = std::str::from_utf8(&bytes) {
        return (s.to_string(), "utf-8");
    }
    let (cow, _enc, had_errors) = encoding_rs::GBK.decode(&bytes);
    if !had_errors {
        return (cow.into_owned(), "gbk");
    }
    (String::from_utf8_lossy(&bytes).into_owned(), "latin-1")
}

fn write_with_encoding(path: &Path, content: &str, encoding: &str) -> std::io::Result<()> {
    let bytes = match encoding {
        "gbk" => encoding_rs::GBK.encode(content).0.into_owned(),
        "utf-16le" => content.encode_utf16().flat_map(|u| u.to_le_bytes()).collect(),
        "utf-16be" => content.encode_utf16().flat_map(|u| u.to_be_bytes()).collect(),
        "utf-8-bom" => {
            let mut v = vec![0xEF, 0xBB, 0xBF];
            v.extend_from_slice(content.as_bytes());
            v
        }
        _ => content.as_bytes().to_vec(),
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, bytes)
}

// ── 目录/搜索 ──

/// 单层目录 (懒加载), 无扩展名白名单, 隐藏特定目录
fn viewer_list_dir(role: &Path, rel_path: &str) -> Vec<Value> {
    // 透明前缀仅用于磁盘定位；item_path 输出保持 role-relative（用原 rel_path，不带 roles/）
    let disk_rel = apply_role_prefix(rel_path, &discover_roles(role));
    let full = if disk_rel.is_empty() {
        role.to_path_buf()
    } else {
        role.join(&disk_rel)
    };
    let visible = config().visible_roots.clone();
    let Ok(entries) = fs::read_dir(&full) else {
        return vec![];
    };
    let mut items: Vec<Value> = entries
        .filter_map(|e| e.ok())
        .filter(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            let is_dir = e.path().is_dir();
            let item_path = if rel_path.is_empty() {
                name.clone()
            } else {
                format!("{}/{}", rel_path, name)
            };
            // root 层 allowlist: rel_path 空 + 配置存在 → 只显白名单内（子目录内全显）
            if rel_path.is_empty() {
                if let Some(ref allow) = visible {
                    if !allow.contains(&name) {
                        return false;
                    }
                }
            }
            !is_hidden_entry(&item_path, &name, is_dir)
        })
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
            let item_path = if rel_path.is_empty() {
                name.clone()
            } else {
                format!("{}/{}", rel_path, name)
            };
            let language = ext.as_deref().map(language_from_ext).unwrap_or("");
            Some(json!({
                "name": name,
                "type": if is_dir { "folder" } else { "file" },
                "extension": ext.map(|e| format!(".{}", e)),
                "path": item_path,
                "size": if is_dir { 0 } else { meta.len() },
                "language": language,
            }))
        })
        .collect();
    items.sort_by(|a, b| {
        let a_folder = a["type"] == "folder";
        let b_folder = b["type"] == "folder";
        b_folder.cmp(&a_folder).then_with(|| {
            a["name"].as_str().unwrap_or("").to_lowercase().cmp(&b["name"].as_str().unwrap_or("").to_lowercase())
        })
    });
    items
}

/// 递归收集所有文件, 供 cmd+P 索引；带 5s TTL 缓存。
fn viewer_collect_all(role: &Path) -> Vec<Value> {
    if let Ok(cache) = COLLECT_CACHE.lock() {
        if let Some((t, v)) = cache.as_ref() {
            if t.elapsed() < COLLECT_CACHE_TTL {
                return v.clone();
            }
        }
    }

    // 并行收集文件路径：rayon 递归遍历，最终统一排序保证结果稳定
    let file_paths = Mutex::new(Vec::<std::path::PathBuf>::new());
    fn walk(dir: &Path, base: &Path, out: &Mutex<Vec<std::path::PathBuf>>) {
        let entries: Vec<_> = fs::read_dir(dir)
            .map(|rd| rd.filter_map(Result::ok).collect())
            .unwrap_or_default();
        entries.par_iter().for_each(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            let p = e.path();
            let rel = p.strip_prefix(base).unwrap_or(&p).to_string_lossy().replace('\\', "/");
            if is_hidden_entry(&rel, &name, p.is_dir()) { return; }
            if p.is_dir() {
                walk(&p, base, out);
            } else if p.is_file() {
                if let Ok(mut guard) = out.lock() {
                    guard.push(p);
                }
            }
        });
    }
    let visible = config().visible_roots.clone();
    match visible {
        Some(allow) => {
            allow.par_iter().for_each(|root_name| {
                walk(&role.join(root_name), role, &file_paths);
            });
        }
        None => walk(role, role, &file_paths),
    }

    let mut paths = file_paths.into_inner().unwrap_or_default();
    paths.sort();
    let out: Vec<Value> = paths
        .into_iter()
        .map(|p| {
            let rel = p.strip_prefix(role).unwrap_or(&p).to_string_lossy().replace('\\', "/");
            let name = p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
            let ext = Path::new(&name).extension()
                .map(|x| x.to_string_lossy().to_lowercase())
                .unwrap_or_default();
            json!({ "path": rel, "name": name, "extension": format!(".{}", ext) })
        })
        .collect();

    if let Ok(mut cache) = COLLECT_CACHE.lock() {
        *cache = Some((Instant::now(), out.clone()));
    }
    out
}

fn viewer_search(role: &Path, query: &str, ext_filter: Option<&str>) -> Vec<Value> {
    if query.is_empty() {
        return Vec::new();
    }
    let q_lower = query.to_lowercase();
    let ext_filter_lc = ext_filter.map(|s| s.to_lowercase());
    let index = get_or_build_search_index(role);
    search_index(&index, &q_lower, &ext_filter_lc)
}

/// 文件是否需要从搜索索引排除：超过大小阈值或属于已知二进制扩展名。
fn should_skip_search_file(name: &str, size: u64, max_bytes: u64) -> bool {
    if size > max_bytes {
        return true;
    }
    let ext = Path::new(name)
        .extension()
        .map(|x| x.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    SEARCH_BINARY_EXTS.contains(&ext.as_str())
}

/// 简单二进制嗅探：前 8KB 出现 NUL 即视为二进制。
fn is_search_binary_content(bytes: &[u8]) -> bool {
    bytes.iter().take(8192).any(|&b| b == 0)
}

fn build_search_index(role: &Path) -> SearchIndex {
    let max_bytes = config().search_max_file_kb.saturating_mul(1024);
    let file_paths = Mutex::new(Vec::<std::path::PathBuf>::new());
    fn walk(dir: &Path, base: &Path, out: &Mutex<Vec<std::path::PathBuf>>) {
        let entries: Vec<_> = fs::read_dir(dir)
            .map(|rd| rd.filter_map(Result::ok).collect())
            .unwrap_or_default();
        entries.par_iter().for_each(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            let p = e.path();
            let rel = p.strip_prefix(base).unwrap_or(&p).to_string_lossy().replace('\\', "/");
            if is_hidden_entry(&rel, &name, p.is_dir()) { return; }
            if p.is_dir() {
                walk(&p, base, out);
            } else if p.is_file() {
                if let Ok(mut guard) = out.lock() {
                    guard.push(p);
                }
            }
        });
    }
    let visible = config().visible_roots.clone();
    match visible {
        Some(allow) => {
            allow.par_iter().for_each(|root_name| {
                walk(&role.join(root_name), role, &file_paths);
            });
        }
        None => walk(role, role, &file_paths),
    }

    let mut paths = file_paths.into_inner().unwrap_or_default();
    paths.sort();
    let files: Vec<SearchFile> = paths
        .par_iter()
        .filter_map(|p| {
            let Ok(meta) = fs::metadata(p) else { return None; };
            let name = p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
            if should_skip_search_file(&name, meta.len(), max_bytes) {
                return None;
            }
            let Ok(bytes) = fs::read(p) else { return None; };
            if is_search_binary_content(&bytes) {
                return None;
            }
            let (content, _enc) = detect_and_read(p);
            if content.is_empty() {
                return None;
            }
            let rel = p.strip_prefix(role).unwrap_or(p.as_path()).to_string_lossy().replace('\\', "/");
            let ext = Path::new(&name)
                .extension()
                .map(|x| x.to_string_lossy().to_lowercase())
                .unwrap_or_default();
            Some(SearchFile {
                rel,
                ext,
                lines: content.lines().map(|s| s.to_string()).collect(),
            })
        })
        .collect();
    SearchIndex { files }
}

fn get_or_build_search_index(role: &Path) -> SearchIndex {
    if let Ok(cache) = SEARCH_INDEX.lock() {
        if let Some((t, index)) = cache.as_ref() {
            if t.elapsed() < SEARCH_INDEX_TTL {
                return index.clone();
            }
        }
    }
    let fresh = build_search_index(role);
    if let Ok(mut cache) = SEARCH_INDEX.lock() {
        *cache = Some((Instant::now(), fresh.clone()));
    }
    fresh
}

fn search_index(index: &SearchIndex, q: &str, ext_filter: &Option<String>) -> Vec<Value> {
    let mut results = Vec::new();
    'outer: for file in &index.files {
        if let Some(ef) = ext_filter {
            if &file.ext != ef {
                continue;
            }
        }
        for (i, line) in file.lines.iter().enumerate() {
            if line.to_lowercase().contains(q) {
                results.push(json!({ "path": file.rel, "line": i + 1, "text": line }));
                if results.len() >= SEARCH_MAX_RESULTS {
                    break 'outer;
                }
            }
        }
    }
    results
}

// ── HTTP 工具 ──

fn http_send(stream: &mut TcpStream, status: u16, status_text: &str, content_type: &str, body: &[u8]) {
    let header = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n\
         Access-Control-Allow-Origin: *\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
        status, status_text, content_type, body.len()
    );
    let _ = stream.write_all(header.as_bytes());
    let _ = stream.write_all(body);
    let _ = stream.flush();
}

fn http_send_cached(stream: &mut TcpStream, status: u16, status_text: &str, content_type: &str, body: &[u8], cache_control: &str) {
    let header = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n\
         Access-Control-Allow-Origin: *\r\nCache-Control: {}\r\nConnection: close\r\n\r\n",
        status, status_text, content_type, body.len(), cache_control
    );
    let _ = stream.write_all(header.as_bytes());
    let _ = stream.write_all(body);
    let _ = stream.flush();
}

fn http_send_json(stream: &mut TcpStream, status: u16, value: Value) {
    let body = serde_json::to_vec(&value).unwrap_or_else(|_| b"{}".to_vec());
    http_send(stream, status, "OK", "application/json; charset=utf-8", &body);
}

fn http_send_error(stream: &mut TcpStream, status: u16, msg: &str) {
    http_send_json(stream, status, json!({ "error": msg }));
}

fn mime_for(path: &Path) -> &'static str {
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
    match ext.as_str() {
        "html" | "htm" => "text/html; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "js" | "mjs" => "application/javascript; charset=utf-8",
        "json" => "application/json; charset=utf-8",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "bmp" => "image/bmp",
        "ico" => "image/x-icon",
        "map" => "application/json; charset=utf-8",
        "txt" | "md" => "text/plain; charset=utf-8",
        "woff" | "woff2" => "font/woff2",
        _ => "application/octet-stream",
    }
}

/// 是否按二进制原始字节处理 (raw 路由/下载打包): 图片类不走 detect_and_read 文本解码,
/// 避免编码转换破坏字节流。svg 亦按原始字节保留 (防止 XML 声明被改写)。
fn is_binary_ext(ext: &str) -> bool {
    matches!(
        ext.to_lowercase().as_str(),
        "png" | "jpg" | "jpeg" | "gif" | "webp" | "bmp" | "ico" | "svg"
    )
}

/// 路径规范化: 折叠 . / .. / 空段 (镜像前端 resolveRelative 的归一逻辑)。
fn normalize_path(p: &str) -> String {
    let mut segs: Vec<&str> = Vec::new();
    for seg in p.split('/') {
        match seg {
            "" | "." => {}
            ".." => { segs.pop(); }
            s => segs.push(s),
        }
    }
    segs.join("/")
}

/// 把 md 内相对/绝对引用解析为 repo 相对路径 (与前端 resolveRelative 等价)。
/// href 以 / 开头 = repo 根相对; 否则相对 basePath 所在目录。
fn resolve_relative(base_path: &str, href: &str) -> Option<String> {
    let target = href.split('#').next().unwrap_or("").split('?').next().unwrap_or("");
    let target = target.trim();
    if target.is_empty() { return None; }
    if let Some(stripped) = target.strip_prefix('/') {
        return Some(normalize_path(stripped));
    }
    let base_dir = base_path.rsplit_once('/').map(|(d, _)| d).unwrap_or("");
    let joined = if base_dir.is_empty() {
        target.to_string()
    } else {
        format!("{}/{}", base_dir, target)
    };
    Some(normalize_path(&joined))
}

/// 图片向上查找 fallback: rel 含 `/images/<name>` 但该路径不存在时,
/// 逐级向上找祖先目录的 `images/<name>`。用于 build.py 类文档: 图片统一放根 images/,
/// md 散布子目录, 引用 `images/xxx` 相对 md 目录解析失败 -> 向上找祖先 images。
/// 仅对原路径不存在的图片请求触发, 不改变正常相对路径语义。
fn find_ancestor_image(role: &Path, rel: &str) -> Option<std::path::PathBuf> {
    let parts: Vec<&str> = rel.split('/').collect();
    let img_idx = parts.iter().rposition(|s| *s == "images")?;
    if img_idx + 1 >= parts.len() { return None; }
    let name = parts[img_idx + 1];
    if name.is_empty() { return None; }
    // 逐级向上: 前缀 parts[0..end], end 从 img_idx-1 递减到 1 (跳过原路径本身 img_idx)
    for end in (1..img_idx).rev() {
        let candidate = format!("{}/images/{}", parts[..end].join("/"), name);
        let p = role.join(&candidate);
        if p.is_file() {
            return Some(p);
        }
    }
    let root = role.join("images").join(name);
    if root.is_file() { return Some(root); }
    None
}

/// 递归收集仓内所有 .md/.markdown 文件 (跳过隐藏配置)。
fn collect_md_files(role: &Path, out: &mut Vec<std::path::PathBuf>) {
    fn walk(dir: &Path, base: &Path, out: &mut Vec<std::path::PathBuf>) {
        let Ok(entries) = fs::read_dir(dir) else { return; };
        for e in entries.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            let p = e.path();
            let rel = p.strip_prefix(base).unwrap_or(&p).to_string_lossy().replace('\\', "/");
            if is_hidden_entry(&rel, &name, p.is_dir()) { continue; }
            if p.is_dir() {
                walk(&p, base, out);
            } else if p.is_file() {
                let ext = p.extension().and_then(|x| x.to_str()).unwrap_or("").to_lowercase();
                if ext == "md" || ext == "markdown" {
                    out.push(p);
                }
            }
        }
    }
    walk(role, role, out);
}

/// 列出工作区所有改动文件 (git status --porcelain, 含未跟踪)。每项为 repo 相对路径。
/// 重命名条目 "R  old -> new" 取 new; 路径含空格时 git 以引号包裹, 去引号。
fn repo_dirty_files(role: &Path) -> Vec<String> {
    let out = std::process::Command::new("git")
        .args(["status", "--porcelain"])
        .current_dir(role)
        .output();
    let mut v = Vec::new();
    if let Ok(o) = out {
        for line in String::from_utf8_lossy(&o.stdout).lines() {
            if line.len() <= 3 { continue; }
            let rest = line[3..].trim();
            let path = if let Some(idx) = rest.find(" -> ") {
                &rest[idx + 4..]
            } else {
                rest
            };
            let path = path.trim_matches('"').replace('\\', "/");
            if !path.is_empty() { v.push(path); }
        }
    }
    v
}

fn url_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let (Some(h), Some(l)) = (
                (bytes[i + 1] as char).to_digit(16),
                (bytes[i + 2] as char).to_digit(16),
            ) {
                out.push((h * 16 + l) as u8);
                i += 3;
                continue;
            }
        } else if bytes[i] == b'+' {
            out.push(b' ');
            i += 1;
            continue;
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

// ── 评论 (comments) ──

/// 从 `roles/<Role>/...` 路径提取角色名。
pub(crate) fn role_from_path(p: &str) -> Option<String> {
    let normalized = p.replace('\\', "/");
    let stripped = normalized.strip_prefix("roles/")?;
    let role = stripped.split('/').next()?;
    if role.is_empty() { return None; }
    Some(role.to_string())
}

/// 加载角色评论 (`roles/<Role>/comments.json`)。文件不存在/解析失败返回空结构。
pub(crate) fn comments_load(role_root: &Path, role_name: &str) -> Value {
    let p = role_root.join("roles").join(role_name).join("comments.json");
    match fs::read_to_string(&p) {
        Ok(s) => serde_json::from_str(&s)
            .unwrap_or_else(|_| json!({"version": 1, "comments": []})),
        Err(_) => json!({"version": 1, "comments": []}),
    }
}

/// 原子写评论: 写 `.tmp` → `fs::rename`。
pub(crate) fn comments_save(role_root: &Path, role_name: &str, v: &Value) -> std::io::Result<()> {
    let dir = role_root.join("roles").join(role_name);
    let target = dir.join("comments.json");
    let tmp = dir.join("comments.json.tmp");
    fs::create_dir_all(&dir)?;
    let data = serde_json::to_vec_pretty(v)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))?;
    fs::write(&tmp, &data)?;
    fs::rename(&tmp, &target)
}

/// 当前时间戳 (epoch 秒字符串, 无 chrono 依赖)。
fn now_ts() -> String {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    format!("{}", dur.as_secs())
}

/// 生成评论 ID: `c-<secs>-<nanos_tail>`。
fn gen_comment_id() -> String {
    let dur = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    format!("c-{}-{:06}", dur.as_secs(), dur.subsec_nanos() % 1_000_000)
}

#[derive(Default)]
struct HttpRequest {
    method: String,
    path: String,
    query: String,
    headers: std::collections::HashMap<String, String>,
    body: Vec<u8>,
}

fn parse_query(q: &str) -> std::collections::HashMap<String, String> {
    let mut m = std::collections::HashMap::new();
    for pair in q.split('&') {
        if pair.is_empty() { continue; }
        let (k, v) = match pair.split_once('=') {
            Some(x) => x,
            None => (pair, ""),
        };
        m.insert(url_decode(k), url_decode(v));
    }
    m
}

fn read_http_request(stream: &mut TcpStream) -> Option<HttpRequest> {
    let mut reader = std::io::BufReader::new(stream.try_clone().ok()?);
    let mut line = String::new();
    if reader.read_line(&mut line).ok()? == 0 { return None; }
    let mut parts = line.trim_end_matches(['\r', '\n']).split(' ');
    let method = parts.next()?.to_string();
    let target = parts.next()?.to_string();
    let _ = parts.next();
    let (path, query) = match target.split_once('?') {
        Some((p, q)) => (p.to_string(), q.to_string()),
        None => (target, String::new()),
    };
    let mut req = HttpRequest { method, path, query, ..Default::default() };
    loop {
        let mut hl = String::new();
        if reader.read_line(&mut hl).ok()? == 0 { break; }
        let h = hl.trim_end_matches(['\r', '\n']);
        if h.is_empty() { break; }
        if let Some((k, v)) = h.split_once(':') {
            req.headers.insert(k.trim().to_lowercase(), v.trim().to_string());
        }
    }
    if let Some(len_str) = req.headers.get("content-length") {
        if let Ok(len) = len_str.parse::<usize>() {
            if len > 0 && len <= HTTP_MAX_BODY {
                let mut body = vec![0u8; len];
                if reader.read_exact(&mut body).is_ok() {
                    req.body = body;
                }
            }
        }
    }
    Some(req)
}

fn serve_static(_role: &Path, req: &HttpRequest, stream: &mut TcpStream) {
    let web_root = config().static_dir.clone();
    let url_path = req.path.trim_start_matches('/');
    let rel = if url_path.is_empty() { "index.html" } else { url_path };
    let safe = match safe_relative_path(&web_root, rel) {
        Some(s) => s,
        None => { http_send_error(stream, 403, "path denied"); return; }
    };
    let full = web_root.join(&safe);
    if !full.exists() || !full.is_file() {
        http_send_error(stream, 404, "not found");
        return;
    }
    match fs::read(&full) {
        Ok(bytes) => {
            let is_html = full.extension().map(|e| e.eq_ignore_ascii_case("html") || e.eq_ignore_ascii_case("htm")).unwrap_or(false);
            let cache_control = if is_html {
                "no-cache"
            } else {
                // 静态资源带版本 query（style.css?v=... / app.js?v=...），可长缓存
                "public, max-age=31536000, immutable"
            };
            http_send_cached(stream, 200, "OK", mime_for(&full), &bytes, cache_control);
        }
        Err(_) => http_send_error(stream, 500, "read failed"),
    }
}

/// 评论 CRUD 路由分发:
/// GET    /api/reader/comments
/// POST   /api/reader/comments
/// POST   /api/reader/comments/<id>/reply
/// PATCH  /api/reader/comments/<id>
/// DELETE /api/reader/comments/<id>
fn handle_comment_routes(
    role: &Path,
    req: &HttpRequest,
    q: &std::collections::HashMap<String, String>,
    stream: &mut TcpStream,
) {
    let path = req.path.as_str();
    match (req.method.as_str(), path) {
        // ── GET: 列出角色的所有评论 ──
        ("GET", "/api/reader/comments") => {
            let p = match q.get("path") {
                Some(s) if !s.is_empty() => s.as_str(),
                _ => { http_send_error(stream, 400, "path required"); return; }
            };
            let role_name = match role_from_path(p) {
                Some(r) => r,
                None => { http_send_error(stream, 400, "path must start with roles/"); return; }
            };
            let data = comments_load(role, &role_name);
            http_send_json(stream, 200, data);
        }
        // ── POST: 新增评论 ──
        ("POST", "/api/reader/comments") => {
            let v: Value = match serde_json::from_slice(&req.body) {
                Ok(v) => v,
                Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
            };
            let p = match v.get("path").and_then(|x| x.as_str()) {
                Some(s) if !s.is_empty() => s.to_string(),
                _ => { http_send_error(stream, 400, "path required"); return; }
            };
            let role_name = match role_from_path(&p) {
                Some(r) => r,
                None => { http_send_error(stream, 400, "path must start with roles/"); return; }
            };
            let kind = v.get("author")
                .and_then(|a| a.get("kind"))
                .and_then(|k| k.as_str())
                .unwrap_or("");
            if kind != "human" && kind != "ai" {
                http_send_error(stream, 400, "author.kind must be 'human' or 'ai'");
                return;
            }
            let body_text = match v.get("body").and_then(|x| x.as_str()) {
                Some(s) if !s.is_empty() => s.to_string(),
                _ => { http_send_error(stream, 400, "body required"); return; }
            };
            let snippet = v.get("snippet").and_then(|x| x.as_str()).unwrap_or("");
            let ctx_before = v.get("contextBefore").and_then(|x| x.as_str()).unwrap_or("");
            let ctx_after = v.get("contextAfter").and_then(|x| x.as_str()).unwrap_or("");
            let now = now_ts();
            let id = gen_comment_id();
            let comment = json!({
                "id": id,
                "path": p,
                "anchor": {
                    "snippet": snippet,
                    "contextBefore": ctx_before,
                    "contextAfter": ctx_after,
                },
                "author": { "kind": kind },
                "body": body_text,
                "createdAt": now,
                "updatedAt": now,
                "status": "open",
                "replies": [],
            });
            let mut data = comments_load(role, &role_name);
            if let Some(arr) = data.get_mut("comments").and_then(|c| c.as_array_mut()) {
                arr.push(comment.clone());
            }
            match comments_save(role, &role_name, &data) {
                Ok(_) => http_send_json(stream, 200, comment),
                Err(e) => http_send_error(stream, 500, &format!("save failed: {}", e)),
            }
        }
        // ── POST /<id>/reply: 回复评论 ──
        ("POST", p) if p.starts_with("/api/reader/comments/") && p.ends_with("/reply") => {
            let comment_id = p["/api/reader/comments/".len()..]
                .trim_end_matches("/reply")
                .to_string();
            let v: Value = match serde_json::from_slice(&req.body) {
                Ok(v) => v,
                Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
            };
            let file_path = match q.get("path") {
                Some(s) if !s.is_empty() => s.as_str(),
                _ => { http_send_error(stream, 400, "path required"); return; }
            };
            let role_name = match role_from_path(file_path) {
                Some(r) => r,
                None => { http_send_error(stream, 400, "path must start with roles/"); return; }
            };
            let kind = v.get("author")
                .and_then(|a| a.get("kind"))
                .and_then(|k| k.as_str())
                .unwrap_or("ai");
            if kind != "human" && kind != "ai" {
                http_send_error(stream, 400, "author.kind must be 'human' or 'ai'");
                return;
            }
            let body_text = match v.get("body").and_then(|x| x.as_str()) {
                Some(s) if !s.is_empty() => s.to_string(),
                _ => { http_send_error(stream, 400, "body required"); return; }
            };
            let now = now_ts();
            let reply = json!({
                "id": gen_comment_id(),
                "author": { "kind": kind },
                "body": body_text,
                "createdAt": now,
            });
            let mut data = comments_load(role, &role_name);
            let mut found = false;
            if let Some(arr) = data.get_mut("comments").and_then(|c| c.as_array_mut()) {
                for c in arr.iter_mut() {
                    if c.get("id").and_then(|i| i.as_str()) == Some(&comment_id) {
                        if let Some(replies) = c.get_mut("replies").and_then(|r| r.as_array_mut()) {
                            replies.push(reply.clone());
                        }
                        c["updatedAt"] = json!(now);
                        found = true;
                        break;
                    }
                }
            }
            if !found {
                http_send_error(stream, 404, "comment not found");
                return;
            }
            match comments_save(role, &role_name, &data) {
                Ok(_) => {
                    let parent = data["comments"].as_array()
                        .and_then(|arr| arr.iter().find(|c| c.get("id").and_then(|i| i.as_str()) == Some(&comment_id)))
                        .cloned()
                        .unwrap_or(json!({}));
                    http_send_json(stream, 200, parent);
                }
                Err(e) => http_send_error(stream, 500, &format!("save failed: {}", e)),
            }
        }
        // ── PATCH /<id>: 更新评论状态/正文 ──
        ("PATCH", p) if p.starts_with("/api/reader/comments/") => {
            let comment_id = p["/api/reader/comments/".len()..].to_string();
            let v: Value = match serde_json::from_slice(&req.body) {
                Ok(v) => v,
                Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
            };
            let file_path = match q.get("path") {
                Some(s) if !s.is_empty() => s.as_str(),
                _ => { http_send_error(stream, 400, "path required"); return; }
            };
            let role_name = match role_from_path(file_path) {
                Some(r) => r,
                None => { http_send_error(stream, 400, "path must start with roles/"); return; }
            };
            let new_status = v.get("status").and_then(|x| x.as_str());
            let new_body = v.get("body").and_then(|x| x.as_str());
            if new_status.is_none() && new_body.is_none() {
                http_send_error(stream, 400, "nothing to patch (status or body required)");
                return;
            }
            if let Some(s) = new_status {
                if s != "open" && s != "resolved" {
                    http_send_error(stream, 400, "status must be 'open' or 'resolved'");
                    return;
                }
            }
            let now = now_ts();
            let mut data = comments_load(role, &role_name);
            let mut updated: Option<Value> = None;
            if let Some(arr) = data.get_mut("comments").and_then(|c| c.as_array_mut()) {
                for c in arr.iter_mut() {
                    if c.get("id").and_then(|i| i.as_str()) == Some(&comment_id) {
                        if let Some(s) = new_status { c["status"] = json!(s); }
                        if let Some(b) = new_body { c["body"] = json!(b); }
                        c["updatedAt"] = json!(now);
                        updated = Some(c.clone());
                        break;
                    }
                }
            }
            match updated {
                Some(comment) => {
                    match comments_save(role, &role_name, &data) {
                        Ok(_) => http_send_json(stream, 200, comment),
                        Err(e) => http_send_error(stream, 500, &format!("save failed: {}", e)),
                    }
                }
                None => http_send_error(stream, 404, "comment not found"),
            }
        }
        // ── DELETE /<id>: 删除评论 ──
        ("DELETE", p) if p.starts_with("/api/reader/comments/") => {
            let comment_id = p["/api/reader/comments/".len()..].to_string();
            let file_path = match q.get("path") {
                Some(s) if !s.is_empty() => s.as_str(),
                _ => { http_send_error(stream, 400, "path required"); return; }
            };
            let role_name = match role_from_path(file_path) {
                Some(r) => r,
                None => { http_send_error(stream, 400, "path must start with roles/"); return; }
            };
            let mut data = comments_load(role, &role_name);
            let mut removed = false;
            if let Some(arr) = data.get_mut("comments").and_then(|c| c.as_array_mut()) {
                let before = arr.len();
                arr.retain(|c| c.get("id").and_then(|i| i.as_str()) != Some(&comment_id));
                removed = arr.len() < before;
            }
            if !removed {
                http_send_error(stream, 404, "comment not found");
                return;
            }
            match comments_save(role, &role_name, &data) {
                Ok(_) => http_send_json(stream, 200, json!({"ok": true})),
                Err(e) => http_send_error(stream, 500, &format!("save failed: {}", e)),
            }
        }
        _ => http_send_error(stream, 404, "unknown comment api"),
    }
}

fn handle_reader_request(role: &Path, req: HttpRequest, stream: &mut TcpStream) {
    let path = req.path.as_str();
    if path.starts_with("/api/reader/") {
        let q = parse_query(&req.query);
        // 写操作（save/create/delete/rename/upload/restore 等）即时失效文件索引缓存
        if req.method == "POST" {
            invalidate_caches();
        }
        // ── 评论路由 (path 含动态 <id> 段, 需前缀匹配) ──
        if path == "/api/reader/comments" || path.starts_with("/api/reader/comments/") {
            handle_comment_routes(role, &req, &q, stream);
            return;
        }
        match (req.method.as_str(), path) {
            ("GET", "/api/reader/tree") => {
                let p = q.get("path").map(|s| s.as_str()).unwrap_or("");
                let rel = match safe_relative_path(role, p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                if q.get("recursive").map(|s| s == "1").unwrap_or(false) {
                    http_send_json(stream, 200, json!(viewer_collect_all(role)));
                } else {
                    http_send_json(stream, 200, json!(viewer_list_dir(role, &rel)));
                }
            }
            ("GET", "/api/reader/file") => {
                let p = match q.get("path") {
                    Some(s) if !s.is_empty() => s.clone(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                let full = role.join(&rel);
                if !full.exists() { http_send_error(stream, 404, "not found"); return; }
                if full.is_dir() { http_send_error(stream, 400, "is a directory"); return; }
                let (content, encoding) = detect_and_read(&full);
                let ext = full.extension().and_then(|e| e.to_str()).unwrap_or("").to_string();
                let language = language_from_ext(&ext).to_string();
                http_send_json(stream, 200, json!({
                    "path": rel, "content": content, "encoding": encoding,
                    "language": language, "extension": ext,
                }));
            }
            ("GET", "/api/reader/raw") => {
                // 原始字节读取 (图片等二进制): 不走 detect_and_read 文本解码,
                // 沙箱同 /file (resolve_rel = safe_relative_path + roles/ 前缀)。
                let p = match q.get("path") {
                    Some(s) if !s.is_empty() => s.clone(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                let mut full = role.join(&rel);
                // images 向上查找 fallback: md 在子目录但引用 images/xxx (build.py 类文档
                // 把图片统一放根 images/) -> 相对 md 目录解析的 子目录/images/xxx 不存在时,
                // 逐级向上找祖先 images/<name>, 不改变正常相对路径语义 (仅原路径 404 时触发)。
                if !full.exists() {
                    if let Some(fb) = find_ancestor_image(role, &rel) {
                        full = fb;
                    }
                }
                if !full.exists() { http_send_error(stream, 404, "not found"); return; }
                if full.is_dir() { http_send_error(stream, 400, "is a directory"); return; }
                match fs::read(&full) {
                    Ok(bytes) => http_send(stream, 200, "OK", mime_for(&full), &bytes),
                    Err(_) => http_send_error(stream, 500, "read failed"),
                }
            }
            ("POST", "/api/reader/upload") => {
                // 粘贴/拖入图片上传: body { ext, content:<base64> }
                // → 内容寻址 (sha1) 落 repo 根 assets/<sha1>.<ext>, 相同内容去重。
                // 扩展白名单 = is_binary_ext, 防上传 .exe 等非图二进制。
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let ext = v.get("ext").and_then(|x| x.as_str()).unwrap_or("bin").to_lowercase();
                if !is_binary_ext(&ext) {
                    http_send_error(stream, 400, "unsupported ext");
                    return;
                }
                let b64 = match v.get("content").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s,
                    _ => { http_send_error(stream, 400, "content required"); return; }
                };
                let bytes = match base64::engine::general_purpose::STANDARD.decode(b64.as_bytes()) {
                    Ok(b) => b,
                    Err(e) => { http_send_error(stream, 400, &format!("base64 decode: {}", e)); return; }
                };
                let mut hasher = Sha1::new();
                hasher.update(&bytes);
                let hex: String = hasher.finalize().iter().map(|b| format!("{:02x}", b)).collect();
                let rel = format!("assets/{}.{}", hex, ext);
                let full = role.join(&rel);
                if !full.exists() {
                    if let Some(parent) = full.parent() { let _ = fs::create_dir_all(parent); }
                    if let Err(e) = fs::write(&full, &bytes) {
                        http_send_error(stream, 500, &format!("write failed: {}", e));
                        return;
                    }
                }
                http_send_json(stream, 200, json!({ "ok": true, "path": rel }));
            }
            ("POST", "/api/reader/save") => {
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let p = match v.get("path").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let content = v.get("content").and_then(|x| x.as_str()).unwrap_or("");
                let encoding = v.get("encoding").and_then(|x| x.as_str()).unwrap_or("utf-8");
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                let full = role.join(&rel);
                match write_with_encoding(&full, content, encoding) {
                    Ok(_) => http_send_json(stream, 200, json!({
                        "ok": true, "path": rel, "encoding": encoding, "bytes": content.len(),
                    })),
                    Err(e) => http_send_error(stream, 500, &format!("write failed: {}", e)),
                }
            }
            ("GET", "/api/reader/search") => {
                let query = q.get("q").map(|s| s.as_str()).unwrap_or("");
                let ext_filter = q.get("ext").map(|s| s.as_str());
                let results = viewer_search(role, query, ext_filter);
                http_send_json(stream, 200, json!({ "results": results }));
            }
            ("POST", "/api/reader/create") => {
                // body: { path, type: "file"|"folder" }
                // path 为相对路径 (含文件名/文件夹名), 自动创建中间目录
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let p = match v.get("path").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let node_type = v.get("type").and_then(|x| x.as_str()).unwrap_or("file");
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                let full = role.join(&rel);
                if full.exists() {
                    http_send_error(stream, 409, "already exists");
                    return;
                }
                let ok = if node_type == "folder" {
                    fs::create_dir_all(&full).is_ok()
                } else {
                    if let Some(parent) = full.parent() {
                        let _ = fs::create_dir_all(parent);
                    }
                    fs::write(&full, "").is_ok()
                };
                if ok {
                    http_send_json(stream, 200, json!({
                        "ok": true, "path": rel, "type": node_type,
                    }));
                } else {
                    http_send_error(stream, 500, "create failed");
                }
            }
            ("POST", "/api/reader/delete") => {
                // body: { path }  移到 temp/trash/<原路径> (回收站), 非 fs::remove
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let p = match v.get("path").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                let full = role.join(&rel);
                if !full.exists() {
                    http_send_error(stream, 404, "not found");
                    return;
                }
                // 回收站路径: temp/trash/<原路径> (保留目录结构, 冲突时新覆盖旧)
                let trash_path = role.join("temp").join("trash").join(&rel);
                if trash_path.exists() {
                    if trash_path.is_dir() { let _ = fs::remove_dir_all(&trash_path); }
                    else { let _ = fs::remove_file(&trash_path); }
                }
                if let Some(parent) = trash_path.parent() { let _ = fs::create_dir_all(parent); }
                let ok = fs::rename(&full, &trash_path).is_ok();
                if ok {
                    let file_name = std::path::Path::new(&rel)
                        .file_name()
                        .and_then(|n| n.to_str())
                        .unwrap_or(&rel);
                    let message = format!("{} trashed", file_name);
                    // git add -A: stage 原文件删除 (temp/trash/ 被 .gitignore 忽略, 不入 git)
                    git_commit(role, &rel, &message, true);
                    http_send_json(stream, 200, json!({
                        "ok": true, "path": rel, "committed": true, "message": message
                    }));
                } else {
                    http_send_error(stream, 500, "delete failed");
                }
            }
            ("POST", "/api/reader/rename") => {
                // body: { from, to }
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let from = match v.get("from").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "from required"); return; }
                };
                let to = match v.get("to").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "to required"); return; }
                };
                let rel_from = match resolve_rel(role, &from) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "from denied"); return; }
                };
                let rel_to = match resolve_rel(role, &to) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "to denied"); return; }
                };
                let src = role.join(&rel_from);
                let dst = role.join(&rel_to);
                if !src.exists() { http_send_error(stream, 404, "source not found"); return; }
                if dst.exists() { http_send_error(stream, 409, "target exists"); return; }
                if let Some(parent) = dst.parent() {
                    let _ = fs::create_dir_all(parent);
                }
                match fs::rename(&src, &dst) {
                    Ok(_) => http_send_json(stream, 200, json!({
                        "ok": true, "from": rel_from, "to": rel_to,
                    })),
                    Err(e) => http_send_error(stream, 500, &format!("rename failed: {}", e)),
                }
            }
            ("POST", "/api/reader/rename-ref") => {
                // 改名被引用资源 (图片/drawio): 重写所有 md 引用 + 移文件 + 一次 git 提交 (可还原)。
                // 比 /rename 多两步: ① 扫仓内 md, 把指向 from 的 ![](from)/<img src> 改指 /<to>;
                // ② git add -A + commit 捕获文件移动 + 引用重写, 历史面板可回滚。
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let from = match v.get("from").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "from required"); return; }
                };
                let to = match v.get("to").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "to required"); return; }
                };
                let rel_from = match resolve_rel(role, &from) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "from denied"); return; }
                };
                let rel_to = match resolve_rel(role, &to) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "to denied"); return; }
                };
                let src = role.join(&rel_from);
                let dst = role.join(&rel_to);
                if !src.exists() { http_send_error(stream, 404, "source not found"); return; }
                if dst.exists() { http_send_error(stream, 409, "target exists"); return; }

                // 扫 md 重写引用: ![alt](ref) / <img src="ref">, 命中 rel_from → 改指 /<rel_to>
                let re = match regex::Regex::new(r#"!\[[^\]]*\]\(([^)]+)\)|<img[^>]*src=["']([^"']+)["']"#) {
                    Ok(r) => r,
                    Err(e) => { http_send_error(stream, 500, &format!("regex: {}", e)); return; }
                };
                let mut rewritten: Vec<String> = Vec::new();
                let mut md_files: Vec<std::path::PathBuf> = Vec::new();
                collect_md_files(role, &mut md_files);
                for md_path in &md_files {
                    let (content, enc) = detect_and_read(md_path);
                    let md_rel = md_path.strip_prefix(role).unwrap_or(md_path).to_string_lossy().replace('\\', "/");
                    let mut out = String::with_capacity(content.len());
                    let mut last = 0usize;
                    for caps in re.captures_iter(&content) {
                        let m = caps.get(0).unwrap();
                        out.push_str(&content[last..m.start()]);
                        let raw_ref = caps.get(1).or_else(|| caps.get(2)).map(|x| x.as_str()).unwrap_or("");
                        let ref_first = raw_ref.split_whitespace().next().unwrap_or(raw_ref);
                        let resolved = resolve_relative(&md_rel, ref_first).unwrap_or_default();
                        if resolved == rel_from {
                            let rest = &raw_ref[ref_first.len()..];
                            let new_ref = format!("/{}{}", rel_to, rest);
                            out.push_str(&m.as_str().replacen(raw_ref, &new_ref, 1));
                        } else {
                            out.push_str(m.as_str());
                        }
                        last = m.end();
                    }
                    out.push_str(&content[last..]);
                    if out != content {
                        let _ = write_with_encoding(md_path, &out, enc);
                        rewritten.push(md_rel);
                    }
                }

                // 移动文件
                if let Some(parent) = dst.parent() { let _ = fs::create_dir_all(parent); }
                if let Err(e) = fs::rename(&src, &dst) {
                    http_send_error(stream, 500, &format!("rename failed: {}", e));
                    return;
                }

                // 一次 git 提交: stage-all 捕获文件移动 + 所有 md 引用重写 (历史面板可还原)
                let short_from = rel_from.rsplit('/').next().unwrap_or(&rel_from);
                let short_to = rel_to.rsplit('/').next().unwrap_or(&rel_to);
                let message = format!("rename {} → {} ({} refs)", short_from, short_to, rewritten.len());
                let committed = git_commit(role, "", &message, true);

                http_send_json(stream, 200, json!({
                    "ok": true, "from": rel_from, "to": rel_to,
                    "rewritten": rewritten, "committed": committed, "message": message,
                }));
            }
            ("POST", "/api/reader/copy") => {
                // body: { from, to }  复制文件或文件夹 (递归); to 必须不存在
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let from = match v.get("from").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "from required"); return; }
                };
                let to = match v.get("to").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "to required"); return; }
                };
                let rel_from = match resolve_rel(role, &from) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "from denied"); return; }
                };
                let rel_to = match resolve_rel(role, &to) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "to denied"); return; }
                };
                let src = role.join(&rel_from);
                let dst = role.join(&rel_to);
                if !src.exists() { http_send_error(stream, 404, "source not found"); return; }
                if dst.exists() { http_send_error(stream, 409, "target exists"); return; }
                if let Some(parent) = dst.parent() {
                    let _ = fs::create_dir_all(parent);
                }
                let ok = copy_recursive(&src, &dst).is_ok();
                if ok {
                    http_send_json(stream, 200, json!({
                        "ok": true, "from": rel_from, "to": rel_to,
                    }));
                } else {
                    http_send_error(stream, 500, "copy failed");
                }
            }
            ("POST", "/api/reader/download") => {
                // body: { paths: ["a/b.md", ...] } → 返回 zip
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let paths: Vec<String> = v.get("paths")
                    .and_then(|x| x.as_array())
                    .map(|arr| arr.iter().filter_map(|p| p.as_str().map(String::from)).collect())
                    .unwrap_or_default();
                if paths.is_empty() {
                    http_send_error(stream, 400, "paths required");
                    return;
                }
                match build_zip(role, &paths) {
                    Ok(zip_bytes) => {
                        let header = format!(
                            "HTTP/1.1 200 OK\r\nContent-Type: application/zip\r\n\
                             Content-Length: {}\r\nContent-Disposition: attachment; filename=\"reader-tabs.zip\"\r\n\
                             Access-Control-Allow-Origin: *\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
                            zip_bytes.len()
                        );
                        let _ = stream.write_all(header.as_bytes());
                        let _ = stream.write_all(&zip_bytes);
                        let _ = stream.flush();
                    }
                    Err(e) => http_send_error(stream, 500, &format!("zip failed: {}", e)),
                }
            }
            ("GET", "/api/reader/history") => {
                let p = match q.get("path") {
                    Some(s) if !s.is_empty() => s.clone(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                let results = file_history(role, &rel);
                http_send_json(stream, 200, json!({ "results": results }));
            }
            ("GET", "/api/reader/version") => {
                let p = match q.get("path") {
                    Some(s) if !s.is_empty() => s.clone(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let hash = match q.get("hash") {
                    Some(s) if !s.is_empty() => s.clone(),
                    _ => { http_send_error(stream, 400, "hash required"); return; }
                };
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                match file_version(role, &rel, &hash) {
                    Some(content) => http_send_json(stream, 200, json!({
                        "path": rel, "hash": hash, "content": content,
                    })),
                    None => http_send_error(stream, 404, "version not found"),
                }
            }
            ("GET", "/api/reader/status") => {
                let p = match q.get("path") {
                    Some(s) if !s.is_empty() => s.clone(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                let dirty = file_is_dirty(role, &rel);
                http_send_json(stream, 200, json!({ "path": rel, "dirty": dirty }));
            }
            ("POST", "/api/reader/commit") => {
                let p = match q.get("path") {
                    Some(s) if !s.is_empty() => s.clone(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                // 可选自定义 commit message
                let v: Value = serde_json::from_slice(&req.body).unwrap_or(json!({}));
                let custom = v.get("message").and_then(|x| x.as_str()).unwrap_or("").trim();
                let file_name = std::path::Path::new(&rel)
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or(&rel);
                let message = if custom.is_empty() {
                    format!("{} archived", file_name)
                } else {
                    custom.to_string()
                };
                if !file_is_dirty(role, &rel) {
                    http_send_json(stream, 200, json!({
                        "ok": true, "committed": false, "reason": "no changes"
                    }));
                    return;
                }
                let ok = git_commit(role, &rel, &message, false);
                if ok {
                    http_send_json(stream, 200, json!({
                        "ok": true, "committed": true, "message": message
                    }));
                } else {
                    http_send_error(stream, 500, "git commit failed");
                }
            }
            ("POST", "/api/reader/snapshot") => {
                // 自动历史快照: git add -A + 提交所有改动 (md 编辑/新增粘贴图等); 无改动 no-op。
                // 兜底 autosave 只落盘不入 git 的缺口, 历史面板可还原。message 自动生成。
                let dirty = repo_dirty_files(role);
                if dirty.is_empty() {
                    http_send_json(stream, 200, json!({ "ok": true, "committed": false, "reason": "no changes" }));
                    return;
                }
                let v: Value = serde_json::from_slice(&req.body).unwrap_or(json!({}));
                let custom = v.get("message").and_then(|x| x.as_str()).unwrap_or("").trim();
                let message = if custom.is_empty() {
                    let preview = dirty.iter().take(3).cloned().collect::<Vec<_>>().join(", ");
                    format!("auto-save ({}): {}", dirty.len(), preview)
                } else {
                    custom.to_string()
                };
                let committed = git_commit(role, "", &message, true);
                http_send_json(stream, 200, json!({
                    "ok": true, "committed": committed, "files": dirty, "message": message,
                }));
            }
            ("POST", "/api/reader/restore") => {
                // body: { path, hash }  历史版本恢复: git show <hash>:<path> 写回 + commit
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let p = match v.get("path").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "path required"); return; }
                };
                let hash = match v.get("hash").and_then(|x| x.as_str()) {
                    Some(s) if !s.is_empty() => s.to_string(),
                    _ => { http_send_error(stream, 400, "hash required"); return; }
                };
                let rel = match resolve_rel(role, &p) {
                    Some(s) => s,
                    None => { http_send_error(stream, 403, "path denied"); return; }
                };
                let content = match file_version(role, &rel, &hash) {
                    Some(c) => c,
                    None => { http_send_error(stream, 404, "version not found"); return; }
                };
                let full = role.join(&rel);
                if let Some(parent) = full.parent() { let _ = fs::create_dir_all(parent); }
                match fs::write(&full, &content) {
                    Ok(_) => {
                        let file_name = std::path::Path::new(&rel)
                            .file_name()
                            .and_then(|n| n.to_str())
                            .unwrap_or(&rel);
                        let short: String = hash.chars().take(7).collect();
                        let message = format!("{} restored from {}", file_name, short);
                        git_commit(role, &rel, &message, false);
                        http_send_json(stream, 200, json!({
                            "ok": true, "path": rel, "committed": true, "message": message
                        }));
                    }
                    Err(e) => http_send_error(stream, 500, &format!("write failed: {}", e)),
                }
            }
            ("GET", "/api/reader/trash/list") => {
                // 递归列 temp/trash/ 下文件, path 为原路径 (相对 role)
                let trash_dir = role.join("temp").join("trash");
                let mut items: Vec<Value> = Vec::new();
                if trash_dir.exists() {
                    fn walk(dir: &Path, base: &Path, out: &mut Vec<Value>) {
                        let Ok(entries) = fs::read_dir(dir) else { return; };
                        for e in entries.flatten() {
                            let p = e.path();
                            if p.is_dir() {
                                walk(&p, base, out);
                            } else if p.is_file() {
                                let rel = p.strip_prefix(base).unwrap_or(&p).to_string_lossy().replace('\\', "/");
                                let meta = e.metadata().ok();
                                let size = meta.as_ref().map(|m| m.len()).unwrap_or(0);
                                let mtime = meta.as_ref()
                                    .and_then(|m| m.modified().ok())
                                    .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                                    .map(|d| d.as_secs())
                                    .unwrap_or(0);
                                out.push(json!({ "path": rel, "size": size, "deleted_at": mtime }));
                            }
                        }
                    }
                    walk(&trash_dir, &trash_dir, &mut items);
                }
                items.sort_by(|a, b| b["deleted_at"].as_u64().cmp(&a["deleted_at"].as_u64()));
                http_send_json(stream, 200, json!({ "items": items }));
            }
            ("POST", "/api/reader/trash/restore") => {
                // body: { paths: ["rel1", ...] }  批量从 .trash 移回原位 + 一次 commit
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let paths: Vec<String> = v.get("paths")
                    .and_then(|x| x.as_array())
                    .map(|arr| arr.iter().filter_map(|p| p.as_str().map(String::from)).collect())
                    .unwrap_or_default();
                if paths.is_empty() { http_send_error(stream, 400, "paths required"); return; }
                let mut restored: Vec<String> = Vec::new();
                let mut failed: Vec<Value> = Vec::new();
                for rel in &paths {
                    let rel_checked = match safe_relative_path(role, rel) {
                        Some(s) => s,
                        None => { failed.push(json!({ "path": rel, "error": "path denied" })); continue; }
                    };
                    let trash_path = role.join("temp").join("trash").join(&rel_checked);
                    let orig_path = role.join(&rel_checked);
                    if !trash_path.exists() {
                        failed.push(json!({ "path": rel, "error": "not in trash" }));
                        continue;
                    }
                    if orig_path.exists() {
                        failed.push(json!({ "path": rel, "error": "target exists" }));
                        continue;
                    }
                    if let Some(parent) = orig_path.parent() { let _ = fs::create_dir_all(parent); }
                    match fs::rename(&trash_path, &orig_path) {
                        Ok(_) => restored.push(rel_checked),
                        Err(e) => failed.push(json!({ "path": rel, "error": e.to_string() })),
                    }
                }
                if !restored.is_empty() {
                    let names: Vec<String> = restored.iter()
                        .map(|p| p.rsplit('/').next().unwrap_or(p).to_string())
                        .collect();
                    let message = if names.len() == 1 {
                        format!("{} restored", names[0])
                    } else {
                        format!("{} files restored: {}", names.len(), names.join(", "))
                    };
                    // is_delete=true → git add -A, 一次 stage 所有还原文件
                    git_commit(role, "", &message, true);
                }
                http_send_json(stream, 200, json!({
                    "ok": true, "restored": restored, "failed": failed
                }));
            }
            ("POST", "/api/reader/trash/purge") => {
                // body: { paths: ["rel1", ...] }  批量彻底删除 .trash 内文件 (无 git 变化)
                let v: Value = match serde_json::from_slice(&req.body) {
                    Ok(v) => v,
                    Err(e) => { http_send_error(stream, 400, &format!("bad json: {}", e)); return; }
                };
                let paths: Vec<String> = v.get("paths")
                    .and_then(|x| x.as_array())
                    .map(|arr| arr.iter().filter_map(|p| p.as_str().map(String::from)).collect())
                    .unwrap_or_default();
                if paths.is_empty() { http_send_error(stream, 400, "paths required"); return; }
                let mut purged: Vec<String> = Vec::new();
                let mut failed: Vec<Value> = Vec::new();
                for rel in &paths {
                    let rel_checked = match safe_relative_path(role, rel) {
                        Some(s) => s,
                        None => { failed.push(json!({ "path": rel, "error": "path denied" })); continue; }
                    };
                    let trash_path = role.join("temp").join("trash").join(&rel_checked);
                    if !trash_path.exists() {
                        failed.push(json!({ "path": rel, "error": "not in trash" }));
                        continue;
                    }
                    let ok = if trash_path.is_dir() { fs::remove_dir_all(&trash_path).is_ok() }
                             else { fs::remove_file(&trash_path).is_ok() };
                    if ok { purged.push(rel_checked); }
                    else { failed.push(json!({ "path": rel, "error": "remove failed" })); }
                }
                http_send_json(stream, 200, json!({
                    "ok": true, "purged": purged, "failed": failed
                }));
            }
            _ => http_send_error(stream, 404, "unknown api"),
        }
        return;
    }
    if req.method == "GET" || req.method == "HEAD" {
        serve_static(role, &req, stream);
    } else {
        http_send_error(stream, 405, "method not allowed");
    }
}

/// 把指定路径列表打包成 zip (按相对路径存储), 返回 zip 字节。
fn build_zip(role: &Path, paths: &[String]) -> std::io::Result<Vec<u8>> {
    let buf = Cursor::new(Vec::new());
    let mut zip = zip::ZipWriter::new(buf);
    let opts = zip::write::FileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);
    for p in paths {
        let rel = match safe_relative_path(role, p) {
            Some(s) => s,
            None => continue,
        };
        let full = role.join(&apply_role_prefix(&rel, &discover_roles(role)));
        if !full.exists() || full.is_dir() {
            continue;
        }
        let ext = full.extension().and_then(|e| e.to_str()).unwrap_or("");
        // 二进制 (图片等) 原始字节直读; 文本走 detect_and_read 编码安全解码
        let bytes: Vec<u8> = if is_binary_ext(ext) {
            match fs::read(&full) {
                Ok(b) => b,
                Err(_) => continue,
            }
        } else {
            detect_and_read(&full).0.into_bytes()
        };
        let zip_path = rel.replace('\\', "/");
        zip.start_file(&zip_path, opts)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))?;
        zip.write_all(&bytes)?;
    }
    let buf = zip.finish()
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e.to_string()))?;
    Ok(buf.into_inner())
}

/// 递归复制: 文件用 fs::copy, 文件夹 DFS 复制 (含空目录)。
fn copy_recursive(src: &Path, dst: &Path) -> std::io::Result<()> {
    if src.is_dir() {
        fs::create_dir_all(dst)?;
        for entry in fs::read_dir(src)? {
            let entry = entry?;
            let child_src = entry.path();
            let child_dst = dst.join(entry.file_name());
            copy_recursive(&child_src, &child_dst)?;
        }
        Ok(())
    } else {
        fs::copy(src, dst).map(|_| ())
    }
}

/// 启动 Web Reader HTTP 服务 (阻塞运行, 独立子服务)。
pub fn run() {
    let role = config().workspace.clone();
    let bind = format!("0.0.0.0:{}", config().port);
    loop {
        let listener = match TcpListener::bind(&bind) {
            Ok(l) => {
                eprintln!("[webreader] listening on {}", bind);
                l
            }
            Err(e) => {
                eprintln!("[webreader] bind {} failed: {}; retrying in 2s", bind, e);
                std::thread::sleep(std::time::Duration::from_secs(2));
                continue;
            }
        };

        for stream in listener.incoming() {
            let mut stream = match stream {
                Ok(s) => s,
                Err(e) => {
                    eprintln!("[webreader] accept failed: {}", e);
                    continue;
                }
            };
            let role_c = role.clone();
            std::thread::spawn(move || {
                let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(15)));
                if let Some(req) = read_http_request(&mut stream) {
                    handle_reader_request(&role_c, req, &mut stream);
                } else {
                    eprintln!("[webreader] Failed to parse HTTP request");
                }
                let _ = stream.shutdown(std::net::Shutdown::Both);
            });
        }

        eprintln!("[webreader] listener on {} exited; retrying in 2s", bind);
        std::thread::sleep(std::time::Duration::from_secs(2));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mime_for_image_exts() {
        let m = |e: &str| mime_for(std::path::Path::new(&format!("x.{}", e)));
        assert_eq!(m("png"), "image/png");
        assert_eq!(m("jpg"), "image/jpeg");
        assert_eq!(m("jpeg"), "image/jpeg");
        assert_eq!(m("gif"), "image/gif");
        assert_eq!(m("webp"), "image/webp");
        assert_eq!(m("bmp"), "image/bmp");
        assert_eq!(m("svg"), "image/svg+xml");
        assert_eq!(m("ico"), "image/x-icon");
    }

    #[test]
    fn is_binary_ext_classification() {
        for e in &["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "svg", "PNG", "JPG"] {
            assert!(is_binary_ext(e), "{} 应识别为二进制", e);
        }
        for e in &["md", "txt", "py", "rs", "json", "html", ""] {
            assert!(!is_binary_ext(e), "{} 不应是二进制", e);
        }
    }

    #[test]
    fn comments_load_missing_returns_empty() {
        let tmp = std::env::temp_dir().join("rm_test_comments_missing");
        let data = comments_load(&tmp, "NonexistentRole");
        assert_eq!(data["version"], 1);
        assert!(data["comments"].is_array());
        assert_eq!(data["comments"].as_array().unwrap().len(), 0);
    }

    #[test]
    fn comments_save_atomic_write() {
        let tmp = std::env::temp_dir().join("rm_test_comments_save");
        let _ = fs::remove_dir_all(&tmp);
        let v = json!({"version": 1, "comments": [{"id": "test-1", "body": "hello"}]});
        comments_save(&tmp, "TestRole", &v).unwrap();
        let reloaded = comments_load(&tmp, "TestRole");
        assert_eq!(reloaded["comments"][0]["id"], "test-1");
        assert_eq!(reloaded["comments"][0]["body"], "hello");
        // .tmp should have been renamed away
        assert!(!tmp.join("roles").join("TestRole").join("comments.json.tmp").exists());
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn role_from_path_extracts_role() {
        assert_eq!(role_from_path("roles/TA/readSrc/00-01.md"), Some("TA".to_string()));
        assert_eq!(role_from_path("roles/CP-DEV-xzmp/L0_Index.md"), Some("CP-DEV-xzmp".to_string()));
        assert_eq!(role_from_path("roles/TA"), Some("TA".to_string()));
        assert_eq!(role_from_path("TA/readSrc/00-01.md"), None); // missing roles/ prefix
        assert_eq!(role_from_path("roles/"), None); // empty role segment
    }

    #[test]
    fn should_skip_search_file_classification() {
        assert!(should_skip_search_file("big.md", 1024 * 1024 + 1, 1024 * 1024));
        assert!(!should_skip_search_file("ok.md", 1024 * 1024, 1024 * 1024));
        assert!(should_skip_search_file("photo.png", 100, 1024 * 1024));
        assert!(!should_skip_search_file("notes.txt", 100, 1024 * 1024));
    }

    #[test]
    fn is_search_binary_content_detects_nul() {
        assert!(is_search_binary_content(&[0x00, 0x01, 0x02]));
        assert!(!is_search_binary_content(b"plain text"));
    }

    #[test]
    fn search_index_matches_lines_and_respects_ext() {
        let index = SearchIndex {
            files: vec![
                SearchFile {
                    rel: "a.md".to_string(),
                    ext: "md".to_string(),
                    lines: vec!["Hello world".to_string(), "second line".to_string()],
                },
                SearchFile {
                    rel: "b.txt".to_string(),
                    ext: "txt".to_string(),
                    lines: vec!["HELLO from txt".to_string()],
                },
            ],
        };
        let all = search_index(&index, "hello", &None);
        assert_eq!(all.len(), 2);
        assert_eq!(all[0]["path"], "a.md");
        assert_eq!(all[0]["line"], 1);
        assert_eq!(all[0]["text"], "Hello world");
        assert_eq!(all[1]["path"], "b.txt");

        let md = search_index(&index, "hello", &Some("md".to_string()));
        assert_eq!(md.len(), 1);
        assert_eq!(md[0]["path"], "a.md");

        let none = search_index(&index, "missing", &None);
        assert!(none.is_empty());
    }

}
