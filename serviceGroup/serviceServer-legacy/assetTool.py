#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""assetTool.py —— 资源抓取端点（背景图 / 页面元数据）CLI 桥接。

**为什么存在**：这两条端点的实现在 Python 侧依赖 `requests` + `BeautifulSoup` +
**Playwright（无头 Chromium）**，还要用 `hashlib.md5` 决定图标缓存名 —— Rust 侧既没有
HTML 解析器也没有浏览器自动化与 MD5，重写等于把整套抓取逻辑再实现一遍并引入多个新依赖。
故沿用本仓既有做法（同 `spideorder.rs` 起 `python spideOnlineLog.py`、U3 的 `luaDataTool.py`）：
**HTTP 面留给 Rust，抓取与缓存留在 Python**。这同时把 SDD N9 说的「playwright 那 1 处抓取」
从**服务启动链**里摘出去了 —— 它现在只在被请求时由独立脚本按需拉起。

**调用契约**（Rust `routes/assets.rs` 以子进程调用）：
    python assetTool.py <action>          # 参数：stdin 的 JSON 对象
    stdout（单行 JSON）:
        {"ok": true,  "body": {...}}                       # 成功，body = 原 Flask 响应体
        {"ok": false, "status": 400|500, "message": "..."}  # 失败，沿用原状态码与文案
    action ∈ fetch-background | fetch-metadata

**与 legacy 的关系**：各 action 是 `CustomRoute/ServiceRoute.py` 同名路由体的**逐条搬运**
（同样的抓取顺序、打分规则、缓存命名、返回字段）。差异只有三处，都是有意为之：
  1. 入参来自 stdin、出参打印 JSON（而非 `request.args` / `jsonify`）；
  2. 路径基准取 `__file__` 所在目录（= legacy 根），不依赖调用方 cwd；
  3. `requests` 关掉 SSL 校验并静音 urllib3 告警（与 legacy `verify=False` 等价）。

**注意 `/static/*` 仍由 legacy 提供**：这里返回的 `/static/cache/backgrounds/...`、
`/static/cache/icons/...` 指向 `<legacy>/src/...`，由 Flask 的 static 目录服务 —— 前台**不要**
收编 `/static` 前缀，保持反代即可。
"""

import hashlib
import json
import os
import sys
import traceback
from datetime import datetime
from urllib.parse import urljoin, urlparse

# stdout 必须 UTF-8（Windows 管道默认可能落 ANSI 代码页，中文会让 Rust 侧 JSON 解析失败）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))

IMPORT_ERROR = None
try:
    import requests
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright

    # legacy 用 verify=False 忽略 SSL 错误; 静音由此产生的 InsecureRequestWarning
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
except Exception as e:  # pragma: no cover - 环境问题分支
    IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
FALLBACK_BG = ("https://webstatic.mihoyo.com/upload/op-public/2023/04/18/"
               "744005e8e34898495944517351119572_7718912217696144990.jpg")
ICON_EXTS = [".png", ".jpg", ".jpeg", ".ico", ".svg", ".webp"]


class BadRequest(Exception):
    def __init__(self, message, status=400):
        super(BadRequest, self).__init__(message)
        self.message = message
        self.status = status


def log(msg):
    """诊断信息**必须走 stderr**：stdout 是 JSON 协议通道，混入任何杂项（哪怕一行中文日志）
    都会让 Rust 侧解析失败 —— 实测踩过：死 URL 那次 `print("爬取页面失败…")` 直接顶掉 JSON，
    前台于是回 500「助手返回无法解析为 JSON」而拿不到真正的兜底响应。
    """
    print(msg, file=sys.stderr)


def _cache_dir(*parts):
    d = os.path.join(ROOT, "src", "cache", *parts)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


# ---------------------------------------------------------------- 背景图
def get_latest_bg_info():
    """扫 `src/cache/backgrounds/bg_*.webp`，按文件名里的日期取最新一份。"""
    cache_dir = os.path.join(ROOT, "src", "cache", "backgrounds")
    bg_files = []
    if os.path.exists(cache_dir):
        for f in os.listdir(cache_dir):
            if f.startswith("bg_") and f.endswith(".webp"):
                date_str = f[3:11]
                if date_str.isdigit():
                    bg_files.append({
                        "path": os.path.join(cache_dir, f),
                        "url": "/static/cache/backgrounds/%s" % f,
                        "date": date_str,
                        "size": os.path.getsize(os.path.join(cache_dir, f)),
                    })
    if not bg_files:
        return None
    bg_files.sort(key=lambda x: x["date"], reverse=True)
    return bg_files[0]


# 与 legacy 逐条一致：挑「面积 > 40000」的候选图，偏好 mihoyo/cloudgame，再按面积降序取第一
_BG_JS = r'''() => {
    const imageCandidates = [];
    document.querySelectorAll('img').forEach(img => {
        if (img.src && img.src.startsWith('http')) {
            imageCandidates.push({
                url: img.src,
                area: img.naturalWidth * img.naturalHeight
            });
        }
    });
    document.querySelectorAll('*').forEach(el => {
        const style = window.getComputedStyle(el);
        const bgImg = style.backgroundImage;
        if (bgImg && bgImg !== 'none' && bgImg.includes('url')) {
            const match = bgImg.match(/url\("?(.+?)"?\)/);
            if (match) {
                let url = match[1];
                if (url.startsWith('//')) url = window.location.protocol + url;
                if (!url.startsWith('http')) url = new URL(url, document.baseURI).href;
                const rect = el.getBoundingClientRect();
                imageCandidates.push({ url: url, area: rect.width * rect.height });
            }
        }
    });
    const largeImages = imageCandidates.filter(item => item.area > 40000);
    if (largeImages.length === 0) return null;
    largeImages.sort((a, b) => {
        const aHas = a.url.includes('mihoyo') || a.url.includes('cloudgame');
        const bHas = b.url.includes('mihoyo') || b.url.includes('cloudgame');
        if (aHas && !bHas) return -1;
        if (!aHas && bHas) return 1;
        return b.area - a.area;
    });
    return largeImages[0].url;
}'''


def h_fetch_background(data):
    """抓取背景图：仅在无背景图或强制刷新时爬取。"""
    force = str(data.get("force", "false")).lower() == "true"
    latest_bg = get_latest_bg_info()

    should_crawl = (not latest_bg) or force
    if not should_crawl and latest_bg:
        return {"success": True, "bg_url": latest_bg["url"], "cached": True, "date": latest_bg["date"]}

    friendlink_path = os.path.join(ROOT, "src", "extern", "friendlink.json")
    spider_url = None
    if os.path.exists(friendlink_path):
        with open(friendlink_path, "r", encoding="utf-8") as f:
            spider_url = json.load(f).get("spiderUrl")

    if not spider_url:
        return {"success": True, "bg_url": FALLBACK_BG}

    bg_url = None
    # 1. 无头浏览器抓候选图（这是 N9 要摘出启动链的那一处 playwright）
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=UA)
        page = context.new_page()
        page.set_default_timeout(15000)
        try:
            page.goto(spider_url, wait_until="networkidle")
            page.wait_for_timeout(2000)
            bg_url = page.evaluate(_BG_JS)
        except Exception as pe:
            log("Playwright error: %s" % pe)  # 与 legacy 同: 失败不抛, 走兜底
        finally:
            browser.close()

    # 2. 找到就下载，并和最新缓存比大小
    if bg_url:
        headers = {"User-Agent": UA, "Referer": spider_url}
        try:
            img_res = requests.get(bg_url, headers=headers, timeout=10, verify=False)
            if img_res.status_code == 200:
                new_content = img_res.content
                new_size = len(new_content)
                if latest_bg and new_size == latest_bg["size"] and not force:
                    log("背景图大小相同 (%s)，跳过保存。" % new_size)
                    return {"success": True, "bg_url": latest_bg["url"], "cached": True, "date": latest_bg["date"]}
                cache_dir = _cache_dir("backgrounds")
                today_str = datetime.now().strftime("%Y%m%d")
                new_filename = "bg_%s.webp" % today_str
                with open(os.path.join(cache_dir, new_filename), "wb") as f:
                    f.write(new_content)
                return {
                    "success": True,
                    "bg_url": "/static/cache/backgrounds/%s" % new_filename,
                    "cached": False,
                    "date": today_str,
                    "size_changed": True,
                }
        except Exception as e:
            log("下载背景图失败: %s" % e)

    # 兜底返回
    if latest_bg:
        return {"success": True, "bg_url": latest_bg["url"], "cached": True,
                "date": latest_bg["date"], "error": "抓取失败，返回旧图"}
    return {"success": True, "bg_url": FALLBACK_BG, "error": "抓取失败且无旧图"}


# ---------------------------------------------------------------- 页面元数据
def get_cached_icon_path(url):
    """按 URL 的 MD5 生成图标缓存基础路径（不含扩展名）。"""
    cache_dir = _cache_dir("icons")
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, url_hash), url_hash


def h_fetch_metadata(data):
    """根据 URL 抓取页面标题和图标，支持本地缓存。"""
    url = data.get("url")
    if not url:
        raise BadRequest("缺少URL参数")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url

    # 1. 查缓存（任意扩展名）
    cache_base_path, url_hash = get_cached_icon_path(url)
    cached_file = None
    for ext in ICON_EXTS:
        if os.path.exists(cache_base_path + ext):
            cached_file = "/static/cache/icons/%s%s" % (url_hash, ext)
            break

    # 即使有缓存也重抓页面拿最新标题
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": url,  # 用当前 URL 作 Referer 绕防盗链
    }
    title = None
    favicon_url = None

    try:
        response = requests.get(url, headers=headers, timeout=5, verify=False)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")

        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        if not title:
            meta_title = soup.find("meta", property="og:title") or soup.find("meta", name="twitter:title")
            if meta_title:
                title = meta_title.get("content")
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text().strip()

        # 有缓存图标 + 抓到标题 → 直接返回
        if cached_file and title:
            return {"success": True, "title": title, "favicon": cached_file, "cached": True}

        # 图标候选：<link rel=*icon*> + msapplication-TileImage
        icon_tags = []
        icon_tags.extend(soup.find_all(
            "link", rel=lambda x: x and ("icon" in x.lower() or "apple-touch-icon" in x.lower())))
        tile_image = soup.find("meta", name="msapplication-TileImage")
        if tile_image:
            icon_tags.append(tile_image)

        best_icon = None
        max_size = 0
        for tag in icon_tags:
            href = tag.get("href") or tag.get("content")
            if not href:
                continue
            current_score = 1
            rel = str(tag.get("rel", "")).lower()
            if "apple-touch-icon" in rel:
                current_score += 10
            if ".png" in href.lower():
                current_score += 5
            sizes = tag.get("sizes", "")
            if sizes and "x" in sizes:
                try:
                    size = int(sizes.split("x")[0])
                    if size > max_size:
                        max_size = size
                        current_score += size // 10
                except Exception:
                    pass
            if not best_icon or current_score > best_icon["score"]:
                best_icon = {"href": href, "score": current_score}

        if best_icon:
            favicon_url = best_icon["href"]
            if not favicon_url.startswith(("http://", "https://")):
                favicon_url = urljoin(url, favicon_url)
    except Exception as crawl_err:
        log("爬取页面失败 (%s): %s" % (url, crawl_err))
        if cached_file:
            return {"success": True, "title": title or url, "favicon": cached_file, "cached": True}

    # 兜底：域名根 favicon.ico
    if not favicon_url:
        parsed = urlparse(url)
        favicon_url = "%s://%s/favicon.ico" % (parsed.scheme, parsed.netloc)

    # 下载并保存图标（仅当没有缓存时）
    if not cached_file:
        try:
            icon_res = requests.get(favicon_url, headers=headers, timeout=5, verify=False)
            if icon_res.status_code == 200:
                content_type = icon_res.headers.get("Content-Type", "").lower()
                ext = ".png"
                if "image/x-icon" in content_type or "vnd.microsoft.icon" in content_type:
                    ext = ".ico"
                elif "image/jpeg" in content_type:
                    ext = ".jpg"
                elif "image/svg" in content_type:
                    ext = ".svg"
                elif "image/gif" in content_type:
                    ext = ".gif"
                elif "image/webp" in content_type:
                    ext = ".webp"
                with open(cache_base_path + ext, "wb") as f:
                    f.write(icon_res.content)
                cached_file = "/static/cache/icons/%s%s" % (url_hash, ext)
        except Exception as e:
            log("下载图标失败 (%s): %s" % (favicon_url, e))

    return {"success": True, "title": title or url, "favicon": cached_file or favicon_url, "cached": False}


HANDLERS = {
    "fetch-background": (h_fetch_background, "抓取背景图失败"),
    "fetch-metadata": (h_fetch_metadata, "抓取元数据失败"),
}


def main(argv):
    action = argv[1] if len(argv) > 1 else ""
    if IMPORT_ERROR:
        print(json.dumps({
            "ok": False,
            "status": 500,
            "message": ("assetTool 环境不可用（缺依赖？）: %s；该脚本需 requests/bs4/playwright"
                        "（Rust 侧可用环境变量 SERVICESVR_PYTHON 指定解释器）" % IMPORT_ERROR),
        }, ensure_ascii=False))
        return 0

    entry = HANDLERS.get(action)
    if entry is None:
        print(json.dumps({
            "ok": False, "status": 400,
            "message": "不支持的动作: %s（可选 %s）" % (action, ", ".join(sorted(HANDLERS))),
        }, ensure_ascii=False))
        return 0

    handler, err_prefix = entry
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            raise BadRequest("参数不是 JSON 对象")
    except BadRequest as e:
        print(json.dumps({"ok": False, "status": e.status, "message": e.message}, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "status": 400, "message": "参数 JSON 解析失败: %s" % e}, ensure_ascii=False))
        return 0

    try:
        body = handler(data)
        print(json.dumps({"ok": True, "body": body}, ensure_ascii=False))
    except BadRequest as e:
        print(json.dumps({"ok": False, "status": e.status, "message": e.message}, ensure_ascii=False))
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"ok": False, "status": 500, "message": "%s: %s" % (err_prefix, e)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
