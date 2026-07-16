#!/usr/bin/env python3
r"""
Debug Relay Server - 真机调试中继服务（多客户端版）

功能：
- HTTP 服务：提供调试前端 UI
- WS 服务：同时接受多个游戏端和浏览器端连接，按客户端订阅路由
- 多客户端隔离：每个游戏端独立缓冲（console/perf/断点/暂停），浏览器下拉选择，互不影响
- Console 全量同步：新订阅获取该客户端历史消息
- 源文件读取：从项目目录读取源码（全局共享，非 per-client）
- 重要事件：实时按订阅路由；历史归档按日 JSONL（全局共享）

用法：
    python debug_relay.py --port 9229 --src "D:/Codlib/douque/xzmx/ClientEngineGame/trunk/assets"

客户端标识由服务端自动生成（#序号 · IP），零游戏端改动。
浏览器通过 {type:"select_client", client_id} 订阅；服务端 replay 该客户端的
console/perf/断点/暂停状态。游戏数据按订阅转发，仅送达订阅该客户端的浏览器。
REST API（/api/eval /api/touch /api/scene_tree /api/perf /api/console ...）
支持可选 ?client= 定位；不传时单客户端自动回退，多客户端返回 409 并列出可选 id。
"""

import os
import sys
import json
import re
import asyncio
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, date
from typing import Set, Dict, Optional, Any
from dataclasses import dataclass, field

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except Exception:
    _HAS_YAML = False

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware
import uvicorn

from pydantic import BaseModel


# ---- Config ----

DEFAULT_PORT = 9229
# 默认扫描 assets 下的所有 .ts / .js 文件
DEFAULT_SRC = "../../../assets"

# 允许的文件扩展名（仅这些类型会被索引）
INDEXED_EXTS = [".ts", ".js"]

# 消息类型枚举
class MsgType:
    # Game -> Relay
    CONSOLE_LOG = "console_log"
    CONSOLE_WARN = "console_warn"
    CONSOLE_ERROR = "console_error"
    CONSOLE_INFO = "console_info"
    SOURCE_LIST = "source_list"
    SOURCE_CONTENT = "source_content"
    BREAKPOINT_HIT = "breakpoint_hit"
    PAUSE_STATE = "pause_state"
    PERF_SNAPSHOT = "perf_snapshot"
    PERF_MARK = "perf_mark"
    RUNTIME_SOURCE = "runtime_source"
    IMPORTANT_EVENT = "important_event"

    # 场景节点树
    SCENE_TREE = "scene_tree"
    SCENE_NODE_INFO = "scene_node_info"

    # Relay -> Game
    REGISTER_BREAKPOINT = "register_breakpoint"
    REMOVE_BREAKPOINT = "remove_breakpoint"
    RESUME = "resume"
    EVAL = "eval"
    FETCH_RUNTIME_SOURCE = "fetch_runtime_source"
    RUNTIME_RELOAD = "runtime_reload"

    # Browser -> Game (场景控制)
    SCENE_GET_TREE = "scene_get_tree"
    SCENE_SET_ACTIVE = "scene_set_active"
    SCENE_GET_NODE_INFO = "scene_get_node_info"
    SCENE_SET_PROPERTY = "scene_set_property"

    # Relay -> Browser
    CONSOLE_BATCH = "console_batch"        # 批量控制台消息（订阅 replay）
    GAME_CONNECTED = "game_connected"
    GAME_DISCONNECTED = "game_disconnected"

    # 多客户端协议
    SELECT_CLIENT = "select_client"        # Browser -> Relay: 订阅某客户端
    CLIENT_LIST = "client_list"            # Relay -> Browser: 当前所有客户端 + 本浏览器订阅
    BREAKPOINTS_STATE = "breakpoints_state"  # Relay -> Browser: 订阅 replay 已注册断点


# ---- State ----

CONSOLE_BUFFER_MAX = 50000
PERF_BUFFER_MAX = 600


@dataclass
class ClientCtx:
    """单个游戏端会话状态（per-client 隔离）。"""
    id: str
    label: str
    ip: str
    ws: WebSocket
    console_buffer: list = field(default_factory=list)
    console_seq: int = 0
    perf_buffer: list = field(default_factory=list)
    # REST->WS 请求/响应关联（单飞 per response_key），per-client 隔离
    response_futures: Dict[str, "asyncio.Future"] = field(default_factory=dict)
    eval_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_eval_future: Optional["asyncio.Future"] = None
    # 断点集合 "file:line"（服务端记录，订阅时 replay）
    breakpoints: set = field(default_factory=set)
    # 暂停状态（订阅时 replay）
    paused: bool = False
    paused_file: Optional[str] = None
    paused_line: Optional[Any] = None


@dataclass(eq=False)
class BrowserCtx:
    """单个浏览器会话 + 当前订阅的客户端 id。
    eq=False 保留 object 默认 identity hash，便于放入 set 去重（按连接实例）。
    """
    ws: WebSocket
    subscribed: Optional[str] = None  # ClientCtx.id 或 None


# 游戏端注册表：client_id -> ClientCtx
clients: Dict[str, ClientCtx] = {}

# 浏览器连接集合
browsers: Set[BrowserCtx] = set()

# 客户端序号（单 event loop，无需锁）
_client_counter: int = 0

# 源文件目录（全局共享，非 per-client）
src_dir: Path = None

# 重要事件存储目录（按日分割 JSONL 文件，全局共享）
events_dir: Path = None

# IP 白名单(可选,未启用时允许所有 IP)
whitelist_enabled: bool = False
whitelist_ips: set = set()

# 行为树可视化配置（行为树 tab，无需游戏端连接）
bt_layers: Dict[str, str] = {}        # layer_key -> 绝对目录路径
bt_template_root: Path = None         # @action 节点->TS 解析根（Template/game）
bt_write_ips: set = {"127.0.0.1", "192.168.41.158"}   # 写操作(编辑/拷贝/回滚) IP 白名单
_bt_node_index: Dict[str, tuple] = {}     # lowercase(name) -> (abs_path, line)
_bt_node_index_key: tuple = None          # (root_str, max_mtime) 缓存键


# ---- Client / Browser helpers ----

def _next_client_id(ip: str):
    """生成自增 client_id 与展示标签。"""
    global _client_counter
    _client_counter += 1
    n = _client_counter
    return f"c{n}", f"#{n} · {ip}"


def _client_summary(c: ClientCtx) -> dict:
    return {"id": c.id, "label": c.label, "ip": c.ip}


def _client_summaries() -> list:
    return [_client_summary(c) for c in clients.values()]


async def _send_ws(ws: WebSocket, msg: dict) -> bool:
    """单 WS 发送，失败返回 False（供调用方清理死连接）。"""
    try:
        await ws.send_text(json.dumps(msg, ensure_ascii=False))
        return True
    except Exception:
        return False


async def _broadcast_client_list():
    """向所有浏览器推送当前客户端列表（各浏览器带自己的 selected 字段）。"""
    if not browsers:
        return
    summaries = _client_summaries()
    dead = []
    for b in browsers:
        msg = {"type": MsgType.CLIENT_LIST, "clients": summaries, "selected": b.subscribed}
        if not await _send_ws(b.ws, msg):
            dead.append(b)
    for b in dead:
        browsers.discard(b)


async def _send_to_subscribers(client_id: str, msg: dict):
    """仅转发给订阅了 client_id 的浏览器。"""
    if not browsers:
        return
    dead = []
    for b in browsers:
        if b.subscribed == client_id:
            if not await _send_ws(b.ws, msg):
                dead.append(b)
    for b in dead:
        browsers.discard(b)


def _resolve_client(client_arg: Optional[str]):
    """解析 REST 的 client 定位参数。

    返回 (ClientCtx, None) 或 (None, JSONResponse 错误)。
    - 指定 id：找不到 -> 404
    - 未指定：0 个 -> 409；1 个 -> 自动回退；>1 个 -> 409 列出可选 id
    """
    if client_arg:
        c = clients.get(client_arg)
        if c is None:
            return None, JSONResponse(
                {"error": f"client not found: {client_arg}", "clients": _client_summaries()},
                status_code=404,
            )
        return c, None
    if len(clients) == 0:
        return None, JSONResponse({"error": "no game client connected"}, status_code=409)
    if len(clients) > 1:
        return None, JSONResponse(
            {"error": "multiple clients connected; specify ?client=<id>",
             "clients": _client_summaries()},
            status_code=409,
        )
    return next(iter(clients.values())), None


def _stamp(msg: dict, client_id: str) -> dict:
    """复制并打 client_id（不修改原 msg）。"""
    out = dict(msg)
    out["client_id"] = client_id
    return out


# ---- IP Whitelist ----

async def _enforce_whitelist(websocket: WebSocket) -> bool:
    """白名单校验。返回 True=放行,False=已拒绝并 close。"""
    if not whitelist_enabled:
        return True
    client_ip = websocket.client.host if websocket.client else "<unknown>"
    if client_ip in whitelist_ips:
        return True
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = websocket.url.path if websocket.url else "?"
    print(
        f"[debug-relay] {ts} REJECT WS connection from {client_ip} "
        f"(endpoint={path}, not in whitelist={sorted(whitelist_ips)})",
        flush=True,
    )
    try:
        await websocket.close(code=1008, reason="ip_not_allowed")
    except Exception:
        pass
    return False


# ---- Important Event Persistence ----

def persist_important_event(msg: dict):
    """将重要事件追加到当天的 JSONL 文件中。

    文件路径: {events_dir}/{category}/{YYYY-MM-DD}.jsonl
    每行一个 JSON 对象，字段: category, name, data, ts, client_id

    历史归档全局共享（非 per-client）；client_id 仅作为记录字段，
    便于后续按客户端过滤查询。实时推送按订阅路由（见 handle_game_message）。
    """
    if not events_dir:
        return

    category = msg.get("category", "unknown")
    safe_category = category.replace("/", "_").replace("\\", "_").replace("..", "_")
    today = date.today().isoformat()

    day_dir = events_dir / safe_category
    day_dir.mkdir(parents=True, exist_ok=True)

    filepath = day_dir / f"{today}.jsonl"

    entry = {
        "category": category,
        "name": msg.get("name", ""),
        "data": msg.get("data", {}),
        "ts": msg.get("ts", datetime.now().isoformat()),
        "client_id": msg.get("client_id"),
    }

    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[debug-relay] failed to persist event: {e}")


# ---- FastAPI App ----

app = FastAPI(title="Debug Relay Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- HTTP Endpoints ----

UI_DIR = Path(__file__).parent / "ui"

@app.get("/")
async def index():
    idx = UI_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx), media_type="text/html")
    return {"status": "debug_relay_ready"}


@app.get("/debug-ui.css")
async def ui_css():
    f = UI_DIR / "debug-ui.css"
    if f.exists():
        return FileResponse(str(f), media_type="text/css")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/scene-panel.css")
async def scene_panel_css():
    f = UI_DIR / "scene-panel.css"
    if f.exists():
        return FileResponse(str(f), media_type="text/css")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/debug-console.js")
async def ui_console_js():
    f = UI_DIR / "debug-console.js"
    if f.exists():
        return FileResponse(str(f), media_type="application/javascript")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/debug-sources.js")
async def ui_sources_js():
    f = UI_DIR / "debug-sources.js"
    if f.exists():
        return FileResponse(str(f), media_type="application/javascript")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/debug-perf.js")
async def ui_perf_js():
    f = UI_DIR / "debug-perf.js"
    if f.exists():
        return FileResponse(str(f), media_type="application/javascript")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/debug-events.js")
async def ui_events_js():
    f = UI_DIR / "debug-events.js"
    if f.exists():
        return FileResponse(str(f), media_type="application/javascript")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/debug-scene.js")
async def ui_scene_js():
    f = UI_DIR / "debug-scene.js"
    if f.exists():
        return FileResponse(str(f), media_type="application/javascript")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/debug-btree.js")
async def ui_btree_js():
    f = UI_DIR / "debug-btree.js"
    if f.exists():
        return FileResponse(str(f), media_type="application/javascript")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/debug-curl.js")
async def ui_curl_js():
    f = UI_DIR / "debug-curl.js"
    if f.exists():
        return FileResponse(str(f), media_type="application/javascript")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "clients": _client_summaries(),
        "client_count": len(clients),
        "browser_count": len(browsers),
    }


# ---- Behavior Tree Visualization API（无需游戏端连接，读文件）----

# 匹配 @action({name:"X"}) / @action({ name: "X" }) 等变体
_BT_ACTION_RE = re.compile(r'@action\s*\(\s*\{\s*name\s*:\s*["\']([^"\']+)["\']')


def _build_bt_node_index():
    """扫描 template_root 下所有 .ts，建 lowercase(name) -> (abs_path, line) 索引。
    按 (root, max_mtime) 缓存，Template 改动自动失效。"""
    global _bt_node_index, _bt_node_index_key
    if not bt_template_root or not bt_template_root.exists():
        _bt_node_index = {}
        _bt_node_index_key = None
        return _bt_node_index

    ts_files = list(bt_template_root.rglob("*.ts"))
    max_mtime = 0.0
    for f in ts_files:
        try:
            mt = f.stat().st_mtime
            if mt > max_mtime:
                max_mtime = mt
        except Exception:
            pass
    cache_key = (str(bt_template_root), max_mtime)
    if _bt_node_index_key == cache_key and _bt_node_index:
        return _bt_node_index

    index: Dict[str, tuple] = {}
    for f in ts_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in _BT_ACTION_RE.finditer(text):
            node_name = m.group(1).lower()
            if node_name not in index:
                line_no = text.count("\n", 0, m.start()) + 1
                index[node_name] = (str(f).replace("\\", "/"), line_no)
    _bt_node_index = index
    _bt_node_index_key = cache_key
    return _bt_node_index


def _resolve_bt_node(name: str) -> dict:
    """节点 name -> {found,file,line,vscodeUrl} 或 {notFound}。"""
    if not name:
        return {"notFound": True, "name": name}
    index = _build_bt_node_index()
    hit = index.get(name.lower())
    if hit:
        abs_path, line = hit
        return {
            "found": True,
            "name": name,
            "file": abs_path,
            "line": line,
            "vscodeUrl": f"vscode://file/{abs_path}:{line}",
        }
    return {"notFound": True, "name": name}


@app.get("/api/bt/layers")
async def bt_layers_list():
    """列出四层行为树 + 各层 .json 树清单（.meta 自动排除）。"""
    out = {}
    for key, dir_path in bt_layers.items():
        d = Path(dir_path)
        trees = []
        if d.exists():
            for f in sorted(d.glob("*.json")):
                if f.name.endswith(".meta"):
                    continue
                trees.append(f.stem)
        out[key] = {"dir": dir_path, "exists": d.exists(), "trees": trees}
    return {"layers": out}


@app.get("/api/bt/tree")
async def bt_tree(layer: str, file: str):
    """返回指定层 + 树文件的解析后 JSON。"""
    dir_path = bt_layers.get(layer)
    if not dir_path:
        return JSONResponse({"error": f"unknown layer: {layer}"}, status_code=404)
    if ".." in file or "/" in file or "\\" in file:
        return JSONResponse({"error": "invalid file name"}, status_code=403)
    f = Path(dir_path) / f"{file}.json"
    if not f.exists():
        return JSONResponse({"error": f"tree not found: {file}"}, status_code=404)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return {"layer": layer, "file": file, "tree": data}
    except Exception as e:
        return JSONResponse({"error": f"parse error: {e}"}, status_code=500)


@app.get("/api/bt/resolve")
async def bt_resolve(name: str):
    """节点 name -> TS 源码位置（vscode:// 跳转）。"""
    return _resolve_bt_node(name)


@app.get("/api/bt/search")
async def bt_search(q: str):
    """自由文本搜索（notFound 节点的兜底定位）。返回命中 file:line 列表。"""
    if not q or not bt_template_root:
        return {"results": []}
    needle = q.lower()
    results = []
    for f in bt_template_root.rglob("*.ts"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        low = text.lower()
        idx = 0
        while True:
            pos = low.find(needle, idx)
            if pos < 0:
                break
            line_no = text.count("\n", 0, pos) + 1
            abs_path = str(f).replace("\\", "/")
            results.append({
                "file": abs_path,
                "line": line_no,
                "vscodeUrl": f"vscode://file/{abs_path}:{line_no}",
            })
            idx = pos + len(needle)
            if len(results) >= 30:
                return {"results": results, "truncated": True}
    return {"results": results}


def _http_get_text(url: str, timeout: int = 15) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "debugRelay/btree"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _parse_btree_log(content: str) -> list:
    """解析运行时日志: 'tree <name>\\n{...json...}' 块序列 -> [{name, tree}]。"""
    trees = []
    lines = content.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if s.startswith("tree "):
            name = s[5:].strip()
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n:
                try:
                    trees.append({"name": name, "tree": json.loads(lines[j])})
                    i = j + 1
                    continue
                except Exception:
                    pass
            i += 1
        else:
            i += 1
    return trees


@app.get("/api/bt/source")
async def bt_source(file: str):
    """读取 Template 内 TS 源码（节点定义），供 Sources 面板展示。仅允许 template_root 下文件。"""
    if not bt_template_root or not bt_template_root.exists():
        return JSONResponse({"error": "template_root not configured"}, status_code=500)
    if ".." in file:
        return JSONResponse({"error": "invalid path"}, status_code=403)
    try:
        f = Path(file).resolve()
        root = bt_template_root.resolve()
    except Exception:
        return JSONResponse({"error": "invalid path"}, status_code=403)
    if not str(f).startswith(str(root)):
        return JSONResponse({"error": "file not under template_root"}, status_code=403)
    if not f.exists() or not f.is_file():
        return JSONResponse({"error": "file not found"}, status_code=404)
    try:
        content = f.read_text(encoding="utf-8", errors="ignore")
        return {"content": content, "path": str(f).replace("\\", "/")}
    except Exception as e:
        return JSONResponse({"error": f"read error: {e}"}, status_code=500)


@app.get("/api/bt/runtime_log")
async def bt_runtime_log(userid: str, date: str = None):
    """按 userid + 日期拉取运行时行为树日志。
    1) 列目录 .../xzmk/{date}/btree/
    2) 找匹配 _{userid}_btrees.txt（多渠道 Android_/iOS_ 等，下划线锚定防部分匹配）
    3) 拉取并解析 tree 块 -> [{name, tree}]
    """
    if not userid:
        return JSONResponse({"error": "userid required"}, status_code=400)
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    base = f"http://logdebug.tcy365.org:2505/upload/xzmk/{date}/btree/"
    try:
        listing = await asyncio.to_thread(_http_get_text, base)
    except Exception as e:
        return JSONResponse({"error": f"fetch listing failed: {e}", "listing_url": base}, status_code=502)
    pat = re.compile(r'href="([^"]*_' + re.escape(userid) + r'_btrees\.txt)"')
    matches = pat.findall(listing)
    if not matches:
        return JSONResponse({"error": f"no btree log for userid {userid} on {date}", "listing_url": base}, status_code=404)
    fname = matches[0]
    log_url = base + fname
    try:
        content = await asyncio.to_thread(_http_get_text, log_url)
    except Exception as e:
        return JSONResponse({"error": f"fetch log failed: {e}", "log_url": log_url}, status_code=502)
    trees = _parse_btree_log(content)
    return {
        "userid": userid,
        "date": date,
        "log_url": log_url,
        "matched_files": matches,
        "tree_count": len(trees),
        "trees": trees,
    }


def _parse_btree_exec(content: str) -> list:
    """解析单树执行日志: 'version N' + 'status <nodeId> <state> <inProps> <outProps> <debug>' 序列。
    多个 version 块 = 多次运行。返回 [{version, events:[{nodeId,state,inProps}]}]。"""
    versions = []
    cur = None
    status_re = re.compile(r'^status\s+(\S+)\s+(\d+)(?:\s+(.*))?$')
    for raw in content.split("\n"):
        s = raw.strip()
        if s.startswith("version "):
            try:
                v = int(s[8:].strip())
            except Exception:
                v = 0
            cur = {"version": v, "events": []}
            versions.append(cur)
        elif s.startswith("status "):
            if cur is None:
                cur = {"version": 0, "events": []}
                versions.append(cur)
            m = status_re.match(s)
            if m:
                rest = m.group(3) or ""
                in_props = rest.split(" ", 1)[0] if rest else ""
                cur["events"].append({
                    "nodeId": m.group(1),
                    "state": int(m.group(2)),
                    "inProps": in_props,
                })
    return versions


@app.get("/api/bt/runtime_exec")
async def bt_runtime_exec(userid: str, tree: str, date: str = None):
    """按 userid + 树名 + 日期拉取单棵树的执行轨迹日志（status 时间线）。
    文件名: {platform}_{userid}_{tree}.txt（下划线锚定防部分匹配）。
    """
    if not userid or not tree:
        return JSONResponse({"error": "userid and tree required"}, status_code=400)
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    base = f"http://logdebug.tcy365.org:2505/upload/xzmk/{date}/btree/"
    try:
        listing = await asyncio.to_thread(_http_get_text, base)
    except Exception as e:
        return JSONResponse({"error": f"fetch listing failed: {e}", "listing_url": base}, status_code=502)
    pat = re.compile(r'href="([^"]*_' + re.escape(userid) + r'_' + re.escape(tree) + r'\.txt)"')
    matches = pat.findall(listing)
    if not matches:
        return JSONResponse({"error": f"no exec log for userid {userid} tree {tree} on {date}", "listing_url": base}, status_code=404)
    log_url = base + matches[0]
    try:
        content = await asyncio.to_thread(_http_get_text, log_url)
    except Exception as e:
        return JSONResponse({"error": f"fetch log failed: {e}", "log_url": log_url}, status_code=502)
    versions = _parse_btree_exec(content)
    return {
        "userid": userid,
        "tree": tree,
        "date": date,
        "log_url": log_url,
        "version_count": len(versions),
        "versions": versions,
    }


@app.get("/api/bt/find_tree")
async def bt_find_tree(name: str):
    """在 override_btree + base_btree 查找树结构（运行时缺口树的结构兜底，nodeId 与 exec 一致）。"""
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    if ".." in name or "/" in name or "\\" in name:
        return JSONResponse({"error": "invalid name"}, status_code=403)
    for layer in ("override_btree", "base_btree"):
        dir_path = bt_layers.get(layer)
        if not dir_path:
            continue
        f = Path(dir_path) / f"{name}.json"
        if f.exists():
            try:
                return {"found": True, "layer": layer, "name": name,
                        "tree": json.loads(f.read_text(encoding="utf-8"))}
            except Exception:
                continue
    return JSONResponse({"found": False, "name": name}, status_code=404)


@app.get("/api/bt/runtime_session")
async def bt_runtime_session(userid: str, date: str = None):
    """拉取整目录运行时日志（聚合，对应行为树调试工具的「拉所有日志」）。
    - btrees.txt: 树结构（reset 后可能只含部分树）
    - {userid}_{tree}.txt: 每树执行轨迹
    树列表 = 结构树 ∪ 有 exec 文件的树（覆盖缺口树）。exec 并行拉取内联返回。
    缺口树（无 runtime 结构）structure=None，前端走 /api/bt/find_tree 用 config 兜底（nodeId 稳定一致）。
    """
    if not userid:
        return JSONResponse({"error": "userid required"}, status_code=400)
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    base = f"http://logdebug.tcy365.org:2505/upload/xzmk/{date}/btree/"
    try:
        listing = await asyncio.to_thread(_http_get_text, base)
    except Exception as e:
        return JSONResponse({"error": f"fetch listing failed: {e}", "listing_url": base}, status_code=502)

    pat_btrees = re.compile(r'href="([^"]*_' + re.escape(userid) + r'_btrees\.txt)"')
    pat_tree = re.compile(r'href="([^"]*_' + re.escape(userid) + r'_([a-zA-Z0-9]+)\.txt)"')
    btrees_match = pat_btrees.findall(listing)
    exec_map = {}
    for fname, tname in pat_tree.findall(listing):
        if tname == "btrees":
            continue
        exec_map[tname] = fname

    async def fetch_text(url: str) -> Optional[str]:
        try:
            return await asyncio.to_thread(_http_get_text, url)
        except Exception:
            return None

    # 并行拉 btrees.txt + 所有 exec 文件
    btrees_task = asyncio.create_task(fetch_text(base + btrees_match[0])) if btrees_match else None
    exec_tasks = {tname: asyncio.create_task(fetch_text(base + fname)) for tname, fname in exec_map.items()}
    btrees_text = await btrees_task if btrees_task else None
    exec_texts = {tname: await task for tname, task in exec_tasks.items()}

    structures = {}
    if btrees_text:
        for t in _parse_btree_log(btrees_text):
            structures[t["name"]] = t["tree"]

    all_names = sorted(set(structures.keys()) | set(exec_map.keys()))
    trees = []
    for name in all_names:
        exec_data = None
        if name in exec_texts and exec_texts[name]:
            versions = _parse_btree_exec(exec_texts[name])
            exec_data = {"file": exec_map.get(name), "version_count": len(versions), "versions": versions}
        trees.append({
            "name": name,
            "hasStructure": name in structures,
            "structure": structures.get(name),
            "hasExec": exec_data is not None,
            "exec": exec_data,
        })
    return {
        "userid": userid,
        "date": date,
        "dir_url": base,
        "tree_count": len(trees),
        "trees": trees,
    }


# ---- Behavior Tree 编辑/写（仅覆写层，git 版本管理，IP 白名单）----

_BT_OVERRIDE_LAYERS = ("override_btree", "override_popup")
_BT_BASE_OF = {"override_btree": "base_btree", "override_popup": "base_popup"}


def _bt_check_write(request: Request):
    """写操作 IP 白名单守卫。非白名单 IP -> 403。"""
    ip = request.client.host if request.client else ""
    if ip not in bt_write_ips:
        raise HTTPException(status_code=403, detail=f"写操作不允许来自 {ip}（仅 {sorted(bt_write_ips)}）")


def _bt_git_root(layer_dir: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             cwd=str(layer_dir), capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _bt_git_rel(layer_dir: str, filename: str) -> Optional[str]:
    """文件相对 git root 的路径（正斜杠）。"""
    root = _bt_git_root(layer_dir)
    if not root:
        return None
    try:
        rel = (Path(layer_dir).resolve().relative_to(Path(root).resolve())) / filename
    except Exception:
        return None
    return str(rel).replace("\\", "/")


def _bt_git_commit(layer_dir: str, filename: str, message: str) -> str:
    """git add + commit 单个文件（不动工作区其它改动）。"""
    root = _bt_git_root(layer_dir)
    rel = _bt_git_rel(layer_dir, filename)
    if not root or not rel:
        return "no-git"
    subprocess.run(["git", "-C", root, "add", "--", rel], capture_output=True, text=True, timeout=10)
    subprocess.run(["git", "-C", root, "commit", "-m", message, "--", rel],
                   capture_output=True, text=True, timeout=10)
    return "ok"


class BtreeCopyReq(BaseModel):
    base_layer: str        # base_btree | base_popup
    name: str


class BtreeSaveReq(BaseModel):
    layer: str             # override_btree | override_popup
    name: str
    tree: dict
    message: str = ""


class BtreeRestoreReq(BaseModel):
    layer: str
    name: str
    hash: str


@app.post("/api/btree/copy")
async def bt_copy(req: BtreeCopyReq, request: Request):
    """拷贝基础层树到覆写层（非覆盖，已存在跳过）。"""
    _bt_check_write(request)
    if req.base_layer not in ("base_btree", "base_popup"):
        raise HTTPException(status_code=400, detail="base_layer 必须 base_btree/base_popup")
    if ".." in req.name or "/" in req.name or "\\" in req.name:
        raise HTTPException(status_code=403, detail="invalid name")
    ov_layer = "override_btree" if req.base_layer == "base_btree" else "override_popup"
    base_dir = bt_layers.get(req.base_layer)
    ov_dir = bt_layers.get(ov_layer)
    if not base_dir or not ov_dir:
        raise HTTPException(status_code=400, detail="层未配置")
    src = Path(base_dir) / f"{req.name}.json"
    dst = Path(ov_dir) / f"{req.name}.json"
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"基础层未找到: {req.name}")
    if dst.exists():
        return {"copied": False, "reason": "exists", "name": req.name}
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    _bt_git_commit(ov_dir, f"{req.name}.json", f"btree copy: {ov_layer}/{req.name} (from {req.base_layer})")
    return {"copied": True, "name": req.name}


@app.post("/api/btree/save")
async def bt_save(req: BtreeSaveReq, request: Request):
    """保存覆写层树（紧凑 JSON）+ git commit。"""
    _bt_check_write(request)
    if req.layer not in _BT_OVERRIDE_LAYERS:
        raise HTTPException(status_code=400, detail="仅覆写层可保存")
    if ".." in req.name or "/" in req.name or "\\" in req.name:
        raise HTTPException(status_code=403, detail="invalid name")
    ov_dir = bt_layers.get(req.layer)
    if not ov_dir:
        raise HTTPException(status_code=400, detail="层未配置")
    f = Path(ov_dir) / f"{req.name}.json"
    # 紧凑 JSON 匹配原 b3 格式（最小 diff）
    f.write_text(json.dumps(req.tree, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    msg = req.message or f"btree edit: {req.layer}/{req.name}"
    git = _bt_git_commit(ov_dir, f"{req.name}.json", msg)
    return {"saved": True, "name": req.name, "git": git}


@app.get("/api/btree/versions")
async def bt_versions(layer: str, name: str):
    """git log 列出该覆写树的历史版本。"""
    if layer not in _BT_OVERRIDE_LAYERS:
        raise HTTPException(status_code=400, detail="仅覆写层有版本历史")
    ov_dir = bt_layers.get(layer)
    if not ov_dir:
        return {"versions": [], "git": False}
    root = _bt_git_root(ov_dir)
    rel = _bt_git_rel(ov_dir, f"{name}.json")
    if not root or not rel:
        return {"versions": [], "git": False}
    out = subprocess.run(["git", "-C", root, "log", "--format=%h|%ci|%s", "-n", "50", "--", rel],
                         capture_output=True, timeout=10)
    versions = []
    for line in out.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            versions.append({"hash": parts[0], "date": parts[1], "subject": parts[2]})
    return {"versions": versions, "git": True}


@app.post("/api/btree/restore")
async def bt_restore(req: BtreeRestoreReq, request: Request):
    """回滚覆写树到某 git 版本（git show hash:path -> 写回 + commit）。"""
    _bt_check_write(request)
    if req.layer not in _BT_OVERRIDE_LAYERS:
        raise HTTPException(status_code=400, detail="仅覆写层可回滚")
    ov_dir = bt_layers.get(req.layer)
    if not ov_dir:
        raise HTTPException(status_code=400, detail="层未配置")
    root = _bt_git_root(ov_dir)
    rel = _bt_git_rel(ov_dir, f"{req.name}.json")
    if not root or not rel:
        raise HTTPException(status_code=500, detail="no git")
    out = subprocess.run(["git", "-C", root, "show", f"{req.hash}:{rel}"],
                         capture_output=True, timeout=10)
    if out.returncode != 0:
        raise HTTPException(status_code=404, detail="hash 未找到")
    Path(ov_dir, f"{req.name}.json").write_text(out.stdout.decode("utf-8", errors="replace"), encoding="utf-8")
    _bt_git_commit(ov_dir, f"{req.name}.json", f"btree restore: {req.layer}/{req.name} -> {req.hash}")
    return {"restored": True, "hash": req.hash}


_BT_CATALOG_STD = {
    "composite": ["MemPriority", "MemSequence", "Sequence", "Priority", "Parallel", "ForEach", "MemPriorityRandom", "PriorityRandom"],
    "decorator": ["Inverter", "Limiter", "Repeater", "ReturnSuccess", "ReturnFailure", "MaxTime", "RepeatUntilFailure", "RepeatUntilSuccess", "InterruptOnFinish", "RecorderStatus"],
    "condition": [],
    "action": [],
}


def _bt_classify(name: str) -> str:
    n = name.lower()
    if n.startswith("con_"): return "condition"
    if any(c.lower() == n for c in _BT_CATALOG_STD["composite"]): return "composite"
    if any(d.lower() == n for d in _BT_CATALOG_STD["decorator"]): return "decorator"
    return "action"


@app.get("/api/btree/nodes_catalog")
async def bt_nodes_catalog():
    """节点 palette：标准组合/装饰 + Template @action 注册表（按分类，原案例）。"""
    catalog = {k: list(v) for k, v in _BT_CATALOG_STD.items() }
    if bt_template_root and bt_template_root.exists():
        seen = {n.lower() for cat in catalog.values() for n in cat}
        for f in bt_template_root.rglob("*.ts"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in _BT_ACTION_RE.finditer(text):
                orig = m.group(1)
                if orig.lower() in seen:
                    continue
                seen.add(orig.lower())
                catalog[_bt_classify(orig)].append(orig)
    for k in catalog:
        catalog[k].sort()
    return {"catalog": catalog}


# ---- Curl 工具（HTTP 连通性测试，服务端代理绕 CORS）----

class CurlRequest(BaseModel):
    url: str = ""
    method: str = "GET"
    headers: dict = {}
    body: str = ""
    cmd: str = ""   # 原始 curl 命令（粘贴整条，优先于上面字段）


def parse_curl_cmd(cmd: str):
    """解析 curl 命令串 -> (url, method, headers, body)。用 shlex 分词，不 subprocess。"""
    import shlex
    try:
        toks = shlex.split(cmd)
    except Exception:
        return None
    url, method, headers, body = "", "GET", {}, ""
    i = 0
    while i < len(toks) and toks[i] == "curl":
        i += 1
    while i < len(toks):
        t = toks[i]
        if t in ("-X", "--request") and i + 1 < len(toks):
            method = toks[i + 1]; i += 2
        elif t in ("-H", "--header") and i + 1 < len(toks):
            h = toks[i + 1]; i += 2
            c = h.find(":")
            if c > 0:
                headers[h[:c].strip()] = h[c + 1:].strip()
        elif t in ("-d", "--data", "--data-raw", "--data-binary") and i + 1 < len(toks):
            body = toks[i + 1]; i += 2
            if method == "GET":
                method = "POST"   # -d 隐含 POST
        elif t in ("-s", "--silent", "-S", "--show-error", "-i", "--include",
                   "-L", "--location", "-k", "--insecure", "--compressed", "-v", "--verbose"):
            i += 1   # 忽略这些 curl 标志
        elif t.startswith("http://") or t.startswith("https://"):
            url = t; i += 1
        else:
            i += 1
    return url, method, headers, body


@app.post("/api/curl")
async def api_curl(req: CurlRequest):
    """服务端代理发起 HTTP 请求，返回 status/headers/body/耗时（绕浏览器 CORS）。
    支持粘贴整条 curl 命令(cmd)或结构化字段。"""
    import urllib.request, urllib.error, time as _time
    if req.cmd and req.cmd.strip():
        parsed = parse_curl_cmd(req.cmd)
        if not parsed:
            return JSONResponse({"error": "curl 命令解析失败"}, status_code=400)
        url, method, headers, body = parsed
    else:
        url, method, headers, body = (req.url or "").strip(), (req.method or "GET").upper(), req.headers or {}, req.body or ""
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return JSONResponse({"error": "url 必须以 http:// 或 https:// 开头"}, status_code=400)

    def _do() -> dict:
        t0 = _time.time()
        data = body.encode("utf-8") if body else None
        r = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                raw = resp.read()
                return {
                    "status": resp.status,
                    "reason": resp.reason,
                    "headers": dict(resp.headers.items()),
                    "body": raw.decode("utf-8", errors="ignore")[:200000],
                    "body_truncated": len(raw) > 200000,
                    "elapsed_ms": int((_time.time() - t0) * 1000),
                    "content_type": resp.headers.get("Content-Type", ""),
                    "final_url": resp.url,
                }
        except urllib.error.HTTPError as e:
            try:
                b = e.read().decode("utf-8", errors="ignore")[:200000]
            except Exception:
                b = ""
            return {
                "status": e.code, "reason": e.reason,
                "headers": dict(e.headers.items()), "body": b,
                "elapsed_ms": int((_time.time() - t0) * 1000),
                "content_type": e.headers.get("Content-Type", ""), "final_url": url,
            }
        except Exception as e:
            return {"error": str(e), "elapsed_ms": int((_time.time() - t0) * 1000)}

    return await asyncio.to_thread(_do)


# ---- HTTP API for MCP/agent (perf/touch/eval) ----

async def _send_eval(expr: str, ctx: ClientCtx, timeout: float = 5.0) -> dict:
    """通过 ctx.ws 发 eval, 关联异步返回的 eval_result(串行, 单 pending future)。"""
    async with ctx.eval_lock:
        loop = asyncio.get_running_loop()
        ctx.pending_eval_future = loop.create_future()
        try:
            await ctx.ws.send_json({"type": MsgType.EVAL, "expr": expr})
        except Exception as e:
            ctx.pending_eval_future = None
            return {"error": f"send failed: {e}"}
        try:
            result = await asyncio.wait_for(ctx.pending_eval_future, timeout=timeout)
        except asyncio.TimeoutError:
            result = {"error": "eval timeout"}
        finally:
            ctx.pending_eval_future = None
        return result


# Cocos 3.8.1 触摸派发: 构造 EventTouch 在场景上 dispatch。
def _touch_js(x: float, y: float, touch_type: str) -> str:
    return (
        "(function(x,y,t){try{"
        "const c=document.querySelector('canvas');"
        "if(c){"
        "const mt=t.endsWith('start')?'mousedown':t.endsWith('move')?'mousemove':t.endsWith('cancel')?'mouseleave':'mouseup';"
        "c.dispatchEvent(new MouseEvent(mt,{clientX:x,clientY:y,bubbles:true}));"
        "return 'browser '+mt+' '+x+','+y;"
        "}"
        "const t0=new cc.Touch(0,x,y);"
        "const ev=new cc.EventTouch([t0],true,t);"
        "ev.setLocation(x,y);"
        "const s=cc.director.getScene();"
        "if(s){s.dispatchEvent(ev);}"
        "return 'synthetic '+t+' '+x+','+y;"
        "}catch(e){return 'err:'+e;}"
        f"}})({x},{y},'{touch_type}')"
    )


@app.post("/api/touch")
async def api_touch(req: Request):
    """派发触摸到指定客户端(eval 转发, 零游戏端改动)。
    body: {"x","y","type"[:start|move|end|cancel], "client"?: id}。
    """
    body = await req.json()
    ctx, err = _resolve_client(body.get("client"))
    if err:
        return err
    x = float(body.get("x", 0))
    y = float(body.get("y", 0))
    t = body.get("type", "touch-start")
    norm = {"start": "touch-start", "down": "touch-start",
            "move": "touch-move",
            "end": "touch-end", "up": "touch-end",
            "cancel": "touch-cancel"}
    t = norm.get(t, t if t.startswith("touch-") else "touch-start")
    return await _send_eval(_touch_js(x, y, t), ctx, timeout=3.0)


# ---- WebSocket Handling ----

async def handle_game_websocket(websocket: WebSocket):
    """处理游戏端连接：注册到 clients 注册表，消息路由到订阅浏览器。"""
    if not await _enforce_whitelist(websocket):
        return

    ip = websocket.client.host if websocket.client else "<unknown>"
    cid, label = _next_client_id(ip)
    ctx = ClientCtx(id=cid, label=label, ip=ip, ws=websocket)

    await websocket.accept()
    clients[cid] = ctx
    print(f"[debug-relay] game connected: {cid} ({label})", flush=True)

    # 通知所有浏览器：客户端列表变化
    await _broadcast_client_list()

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                continue
            await handle_game_message(msg, ctx)
    except WebSocketDisconnect:
        pass
    finally:
        clients.pop(cid, None)
        # 通知订阅了该客户端的浏览器：已断开
        await _send_to_subscribers(cid, {
            "type": MsgType.GAME_DISCONNECTED,
            "client_id": cid,
            "ts": datetime.now().isoformat(),
        })
        # 刷新所有浏览器的客户端列表（该客户端已移除）
        await _broadcast_client_list()
        print(f"[debug-relay] game disconnected: {cid}", flush=True)


async def handle_browser_websocket(websocket: WebSocket):
    """处理浏览器端连接：发送 client_list，等待 select_client 订阅。"""
    if not await _enforce_whitelist(websocket):
        return

    await websocket.accept()
    bctx = BrowserCtx(ws=websocket)
    browsers.add(bctx)

    # 立即推送当前客户端列表（selected=null，尚未订阅）
    await _send_ws(websocket, {
        "type": MsgType.CLIENT_LIST,
        "clients": _client_summaries(),
        "selected": None,
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                continue
            await handle_browser_message(msg, bctx)
    except WebSocketDisconnect:
        pass
    finally:
        browsers.discard(bctx)


async def _replay_to_browser(bctx: BrowserCtx):
    """订阅后向该浏览器 replay 所订阅客户端的完整状态。"""
    cid = bctx.subscribed
    if cid is None or cid not in clients:
        return
    ctx = clients[cid]
    ts = datetime.now().isoformat()

    # 游戏连接状态
    await _send_ws(bctx.ws, {"type": MsgType.GAME_CONNECTED, "client_id": cid, "ts": ts})

    # Console 历史
    if ctx.console_buffer:
        await _send_ws(bctx.ws, {
            "type": MsgType.CONSOLE_BATCH,
            "client_id": cid,
            "messages": ctx.console_buffer,
        })

    # Perf 历史
    if ctx.perf_buffer:
        await _send_ws(bctx.ws, {
            "type": "perf_history",
            "client_id": cid,
            "snapshots": ctx.perf_buffer,
        })

    # 已注册断点
    bps = []
    for key in ctx.breakpoints:
        f, _, l = key.partition(":")
        bps.append({"file": f, "line": l})
    await _send_ws(bctx.ws, {
        "type": MsgType.BREAKPOINTS_STATE,
        "client_id": cid,
        "breakpoints": bps,
    })

    # 暂停状态
    if ctx.paused:
        await _send_ws(bctx.ws, {
            "type": MsgType.PAUSE_STATE,
            "client_id": cid,
            "paused": True,
            "file": ctx.paused_file,
            "line": ctx.paused_line,
        })


async def handle_game_message(msg: dict, ctx: ClientCtx):
    """处理来自游戏端的消息：per-client 缓冲 + 按订阅转发。"""
    cid = ctx.id
    msg_type = msg.get("type")

    if msg_type in (MsgType.CONSOLE_LOG, MsgType.CONSOLE_WARN,
                    MsgType.CONSOLE_ERROR, MsgType.CONSOLE_INFO):
        ctx.console_seq += 1
        entry = {
            "seq": ctx.console_seq,
            "type": msg_type,
            "content": msg.get("content", ""),
            "ts": msg.get("ts", datetime.now().isoformat()),
            "client_id": cid,
        }
        if msg.get("tag") is not None:
            entry["tag"] = msg["tag"]
        ctx.console_buffer.append(entry)
        if len(ctx.console_buffer) > CONSOLE_BUFFER_MAX:
            ctx.console_buffer.pop(0)
        await _send_to_subscribers(cid, entry)

    elif msg_type == MsgType.PERF_SNAPSHOT:
        snap = _stamp(msg, cid)
        ctx.perf_buffer.append(snap)
        if len(ctx.perf_buffer) > PERF_BUFFER_MAX:
            ctx.perf_buffer.pop(0)
        if len(ctx.perf_buffer) % 30 == 0:
            print(f"[debug-relay] {cid} perf_buffer size={len(ctx.perf_buffer)} "
                  f"browsers={len(browsers)} latest_fps={msg.get('fps')}")
        await _send_to_subscribers(cid, snap)

    elif msg_type == MsgType.PERF_MARK:
        await _send_to_subscribers(cid, _stamp(msg, cid))

    elif msg_type in (MsgType.SOURCE_LIST, MsgType.SOURCE_CONTENT, MsgType.RUNTIME_SOURCE):
        await _send_to_subscribers(cid, _stamp(msg, cid))

    elif msg_type == MsgType.BREAKPOINT_HIT:
        ctx.paused = True
        ctx.paused_file = msg.get("file")
        ctx.paused_line = msg.get("line") if msg.get("line") is not None else msg.get("func")
        await _send_to_subscribers(cid, _stamp(msg, cid))

    elif msg_type == MsgType.PAUSE_STATE:
        if msg.get("paused") is False:
            ctx.paused = False
            ctx.paused_file = None
            ctx.paused_line = None
        await _send_to_subscribers(cid, _stamp(msg, cid))

    elif msg_type == MsgType.IMPORTANT_EVENT:
        stamped = _stamp(msg, cid)
        persist_important_event(stamped)
        await _send_to_subscribers(cid, stamped)

    elif msg_type in (MsgType.SCENE_TREE, MsgType.SCENE_NODE_INFO):
        _resolve_response_future(ctx, msg_type, msg)
        await _send_to_subscribers(cid, _stamp(msg, cid))

    # eval 结果：resolve REST 等待中的 future（无 type 字段，靠 eval_result 判断），再转发
    if "eval_result" in msg:
        _resolve_response_future(ctx, MsgType.EVAL, msg)
        await _send_to_subscribers(cid, _stamp(msg, cid))


async def handle_browser_message(msg: dict, bctx: BrowserCtx):
    """处理来自浏览器的消息。"""
    msg_type = msg.get("type")

    if msg_type == MsgType.SELECT_CLIENT:
        cid = msg.get("client_id")
        bctx.subscribed = cid if (cid and cid in clients) else None
        await _replay_to_browser(bctx)
        # 回送 client_list（带 selected 确认）
        await _send_ws(bctx.ws, {
            "type": MsgType.CLIENT_LIST,
            "clients": _client_summaries(),
            "selected": bctx.subscribed,
        })
        return

    # 其余消息转发给所订阅客户端的游戏端
    cid = bctx.subscribed
    ctx = clients.get(cid) if cid else None
    if ctx is None:
        return

    if msg_type == MsgType.REGISTER_BREAKPOINT:
        key = f"{msg.get('file')}:{msg.get('line')}"
        ctx.breakpoints.add(key)
        await ctx.ws.send_json(msg)
    elif msg_type == MsgType.REMOVE_BREAKPOINT:
        key = f"{msg.get('file')}:{msg.get('line')}"
        ctx.breakpoints.discard(key)
        await ctx.ws.send_json(msg)
    elif msg_type in (MsgType.RESUME, MsgType.EVAL, MsgType.RUNTIME_RELOAD,
                      MsgType.SCENE_GET_TREE, MsgType.SCENE_SET_ACTIVE,
                      MsgType.SCENE_GET_NODE_INFO, MsgType.SCENE_SET_PROPERTY):
        await ctx.ws.send_json(msg)


# ---- Source File API (全局共享，非 per-client) ----

@app.get("/api/sources")
async def list_sources():
    if not src_dir or not src_dir.exists():
        return {"files": [], "error": "src_dir not configured (run with --src)"}

    files = []
    for ext in INDEXED_EXTS:
        for f in src_dir.rglob(f"*{ext}"):
            if '.meta' in f.name or 'node_modules' in f.parts:
                continue
            rel = f.relative_to(src_dir)
            files.append(str(rel).replace("\\", "/"))

    return {"files": sorted(files)}


@app.get("/api/source")
async def get_source(path: str):
    if not src_dir or not src_dir.exists():
        return JSONResponse({"error": "src_dir not configured (run with --src)"}, status_code=500)

    if ".." in path:
        return JSONResponse({"error": "invalid path: .. not allowed"}, status_code=403)

    safe_path = path.replace("/", os.sep)
    full_path = src_dir / safe_path

    try:
        full_path = full_path.resolve()
        src_dir_resolved = src_dir.resolve()
        if not str(full_path).startswith(str(src_dir_resolved)):
            return JSONResponse({"error": "invalid path: escape from src_dir"}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": f"invalid path: {e}"}, status_code=403)

    if not full_path.exists():
        return JSONResponse({"error": f"file not found: {path}"}, status_code=404)

    try:
        content = full_path.read_text(encoding="utf-8")
        return {"content": content, "path": path}
    except Exception as e:
        return JSONResponse({"error": f"read error: {e}"}, status_code=500)


# ---- Clients API ----

@app.get("/api/clients")
async def api_clients():
    """列出所有已连接的游戏客户端（id/label/ip）。"""
    return {"clients": _client_summaries(), "count": len(clients)}


# ---- Runtime Control API ----

@app.post("/api/runtime/reload")
async def reload_runtime(client: str = None):
    """刷新指定客户端的 Web preview runtime。?client=id（单客户端可省略）。"""
    ctx, err = _resolve_client(client)
    if err:
        return err
    msg = {
        "type": MsgType.RUNTIME_RELOAD,
        "ts": datetime.now().isoformat(),
        "source": "http_api",
    }
    try:
        await ctx.ws.send_json(msg)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"send failed: {e}"}, status_code=500)

    return {
        "ok": True,
        "message": "runtime_reload sent to game",
        "client_id": ctx.id,
        "ts": msg["ts"],
    }


# ---- REST->WS Bridge (请求/响应关联, 单飞 per response_key, per-client) ----

class EvalRequest(BaseModel):
    expr: str
    timeout: float = 5.0
    client: Optional[str] = None


def _resolve_response_future(ctx: ClientCtx, key: str, msg: dict) -> None:
    """把游戏端响应消息 resolve 给等待中的 REST future (若存在)。"""
    fut = ctx.response_futures.pop(key, None)
    if fut is not None and not fut.done():
        try:
            fut.set_result(msg)
        except asyncio.InvalidStateError:
            pass


async def _send_game_and_await(msg: dict, response_key: str, ctx: ClientCtx, timeout: float = 8.0):
    """通过 ctx.ws 发消息给游戏端, 等待匹配响应。单飞 per response_key per client。"""
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    stale = ctx.response_futures.get(response_key)
    if stale is not None and not stale.done():
        stale.cancel()
    ctx.response_futures[response_key] = fut

    try:
        await ctx.ws.send_json(msg)
    except Exception as e:
        ctx.response_futures.pop(response_key, None)
        return JSONResponse({"ok": False, "error": f"send failed: {e}"}, status_code=500)

    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        ctx.response_futures.pop(response_key, None)
        return JSONResponse({"ok": False, "error": f"timeout waiting for {response_key}"}, status_code=504)


@app.post("/api/eval")
async def api_eval(req: EvalRequest):
    """在指定客户端执行 JS 表达式, 返回 {eval_result: "..."}。
    body: {"expr","timeout"?,"client"?}。单客户端可省略 client。
    """
    ctx, err = _resolve_client(req.client)
    if err:
        return err
    msg = {"type": MsgType.EVAL, "expr": req.expr}
    return await _send_game_and_await(msg, MsgType.EVAL, ctx, timeout=max(req.timeout + 3.0, 8.0))


@app.get("/api/scene_tree")
async def api_scene_tree(client: str = None):
    """获取指定客户端运行中场景的节点树快照。?client=id。"""
    ctx, err = _resolve_client(client)
    if err:
        return err
    return await _send_game_and_await({"type": MsgType.SCENE_GET_TREE}, MsgType.SCENE_TREE, ctx, timeout=8.0)


@app.get("/api/scene_node_info")
async def api_scene_node_info(path: str, client: str = None):
    """获取指定客户端指定路径节点的详情。?path=&client=id。"""
    ctx, err = _resolve_client(client)
    if err:
        return err
    return await _send_game_and_await(
        {"type": MsgType.SCENE_GET_NODE_INFO, "path": path},
        MsgType.SCENE_NODE_INFO, ctx, timeout=8.0,
    )


@app.get("/api/perf")
async def api_perf(limit: int = 20, client: str = None):
    """读指定客户端最近 N 条 perf_snapshot（从该客户端 perf_buffer 切片）。"""
    ctx, err = _resolve_client(client)
    if err:
        return err
    n = max(1, min(int(limit), len(ctx.perf_buffer)))
    return {
        "client_id": ctx.id,
        "snapshots": ctx.perf_buffer[-n:] if n else [],
        "count": n,
        "buffer_total": len(ctx.perf_buffer),
    }


@app.get("/api/console")
async def api_console(limit: int = 100, level: str = None, since_seq: int = 0, client: str = None):
    """读指定客户端 console_buffer（从内存切片）。limit/since_seq/level 过滤。"""
    ctx, err = _resolve_client(client)
    if err:
        return err
    msgs = ctx.console_buffer
    if since_seq > 0:
        msgs = [m for m in msgs if m.get("seq", 0) > since_seq]
    if level:
        lv = level.lower()
        msgs = [m for m in msgs if str(m.get("type", "")).endswith(lv)]
    n = max(1, min(int(limit), len(msgs)))
    return {
        "client_id": ctx.id,
        "messages": msgs[-n:] if n else [],
        "count": n,
        "buffer_total": len(ctx.console_buffer),
    }


# ---- Important Event Query API (历史归档全局共享) ----

@app.get("/api/events")
async def query_events(category: str = None, date: str = None, limit: int = 100):
    """查询按日归档的重要事件。

    参数:
      category: 事件分类 (如 "enter_room")，不传则返回所有分类
      date:     日期 (如 "2025-01-15")，不传则返回最近一天
      limit:    返回条数上限 (默认 100)
    """
    if not events_dir or not events_dir.exists():
        return {"events": [], "count": 0, "date": date, "category": category,
                "error": "events_dir not configured (run with --events-dir)"}

    if category:
        safe_category = category.replace("/", "_").replace("\\", "_").replace("..", "_")
        scan_dirs = [events_dir / safe_category]
    else:
        scan_dirs = [d for d in events_dir.iterdir() if d.is_dir()]

    target_date = date or datetime.now().date().isoformat()

    events = []
    for d in scan_dirs:
        if not d.exists():
            continue
        filepath = d / f"{target_date}.jsonl"
        if not filepath.exists():
            continue
        try:
            lines = filepath.read_text(encoding="utf-8").strip().split("\n")
            for i, line in enumerate(lines[-limit:]):
                entry = json.loads(line)
                entry["_idx"] = i
                entry["_category"] = d.name
                events.append(entry)
        except Exception:
            pass

    return {
        "events": events[-limit:],
        "count": len(events),
        "date": target_date,
        "category": category,
    }


@app.get("/api/events/dates")
async def list_event_dates(category: str = None):
    """列出可查询的日期列表。"""
    if not events_dir or not events_dir.exists():
        return {"dates": [], "categories": [],
                "error": "events_dir not configured"}

    categories = []
    all_dates = []

    scan_dirs = []
    if category:
        safe_category = category.replace("/", "_").replace("\\", "_").replace("..", "_")
        scan_dirs = [events_dir / safe_category]
    else:
        scan_dirs = [d for d in events_dir.iterdir() if d.is_dir()]

    for d in scan_dirs:
        if not d.exists():
            continue
        cat_name = d.name
        categories.append(cat_name)
        for f in d.glob("*.jsonl"):
            date_str = f.stem
            all_dates.append({"category": cat_name, "date": date_str})

    return {"dates": sorted(all_dates, key=lambda x: x["date"], reverse=True), "categories": sorted(categories)}


@app.delete("/api/events")
async def delete_event(category: str, date: str, index: int):
    """删除指定分类/日期下第 index 条事件记录（0-based）。"""
    if not events_dir or not events_dir.exists():
        return JSONResponse({"ok": False, "error": "events_dir not configured"}, status_code=500)

    safe_category = category.replace("/", "_").replace("\\", "_").replace("..", "_")
    filepath = events_dir / safe_category / f"{date}.jsonl"

    if not filepath.exists():
        return JSONResponse({"ok": False, "error": f"file not found: {category}/{date}"}, status_code=404)

    try:
        lines = filepath.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"read error: {e}"}, status_code=500)

    if index < 0 or index >= len(lines):
        return JSONResponse({"ok": False, "error": f"index out of range: {index}/{len(lines)}"}, status_code=400)

    del lines[index]
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            if lines:
                f.write("\n".join(lines) + "\n")
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"write error: {e}"}, status_code=500)

    return {"ok": True, "remaining": len(lines), "category": category, "date": date}


# ---- WebSocket Routes ----

@app.websocket("/ws/game")
async def ws_game(websocket: WebSocket):
    await handle_game_websocket(websocket)


@app.websocket("/ws/browser")
async def ws_browser(websocket: WebSocket):
    await handle_browser_websocket(websocket)


# ---- Config File ----

CONFIG_CANDIDATES = ("debug_relay.config.json", "debug_relay.config.yaml", "debug_relay.config.yml")


def _load_config(path: Path) -> dict:
    if not path or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        if not _HAS_YAML:
            print(f"[debug-relay] {path} 需要 PyYAML,但未安装,跳过")
            return {}
        return yaml.safe_load(text) or {}
    if suffix == ".json":
        try:
            return json.loads(text)
        except Exception as e:
            print(f"[debug-relay] 解析 JSON 配置失败 {path}: {e}")
            return {}
    try:
        return json.loads(text)
    except Exception:
        if _HAS_YAML:
            try:
                return yaml.safe_load(text) or {}
            except Exception:
                return {}
        return {}


# ---- CLI ----

def parse_args():
    parser = argparse.ArgumentParser(description="Debug Relay Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--src", default=None, help="Source directory to serve (默认读 config source_dir)")
    parser.add_argument("--events-dir", default=None,
                        help="Directory to persist important events (按日归档 JSONL)")
    parser.add_argument("--whitelist-enable", action="store_true",
                        help="启用 IP 白名单(仅白名单内 IP 可连 WS)")
    parser.add_argument("--whitelist-ips", default="",
                        help="白名单 IP 列表,逗号分隔,需 --whitelist-enable 生效")
    parser.add_argument("--config", default=None,
                        help="配置文件路径(JSON/YAML),支持 whitelist.enabled / whitelist.ips;CLI 显式值覆盖")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # src_dir 延后解析（需读 config source_dir 兜底）-> 先占位，cfg 加载后定值
    src_dir = None

    if args.events_dir:
        events_dir = Path(args.events_dir).resolve()
        events_dir.mkdir(parents=True, exist_ok=True)
    else:
        events_dir = Path(__file__).parent / "events"
        events_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = None
    if args.config:
        cfg_path = Path(args.config).resolve()
    else:
        base = Path(__file__).parent
        for name in CONFIG_CANDIDATES:
            p = base / name
            if p.exists():
                cfg_path = p
                break

    cfg = _load_config(cfg_path) if cfg_path else {}
    # 源码目录: --src > config source_dir > 默认（行为树/Sources 不依赖设备，以本机代码为准）
    _src_arg = args.src or (cfg.get("source_dir") if isinstance(cfg, dict) else None) or DEFAULT_SRC
    src_dir = Path(_src_arg).resolve()
    wl_cfg = cfg.get("whitelist") or {} if isinstance(cfg, dict) else {}
    cfg_enabled = bool(wl_cfg.get("enabled", False))
    cfg_ip_list = wl_cfg.get("ips") or []
    if not isinstance(cfg_ip_list, list):
        cfg_ip_list = []
    cfg_ip_set = {str(x).strip() for x in cfg_ip_list if str(x).strip()}

    cli_ips = {ip.strip() for ip in args.whitelist_ips.split(",") if ip.strip()}
    whitelist_ips = cli_ips if cli_ips else cfg_ip_set
    whitelist_enabled = bool(args.whitelist_enable) or cfg_enabled
    wl_source_parts = []
    if args.whitelist_enable or cli_ips:
        wl_source_parts.append("CLI")
    if cfg_path and (cfg_enabled or cfg_ip_set):
        wl_source_parts.append(str(cfg_path))

    if whitelist_enabled:
        if not whitelist_ips:
            print("WARNING: IP 白名单已启用但 IP 列表为空,将拒绝所有连接")
        else:
            src = "+".join(wl_source_parts) if wl_source_parts else "?"
            print(f"IP 白名单已启用: {sorted(whitelist_ips)} (来源: {src})")
    else:
        print("IP 白名单未启用,允许所有 IP 连接")

    # 行为树可视化配置（行为树 tab）
    bt_cfg = cfg.get("btree") or {} if isinstance(cfg, dict) else {}
    bt_layers_raw = bt_cfg.get("layers") or {}
    bt_layers = {}
    for _k, _v in bt_layers_raw.items():
        if _v:
            try:
                bt_layers[_k] = str(Path(_v).resolve())
            except Exception:
                bt_layers[_k] = str(_v)
    _tpl = bt_cfg.get("template_root")
    bt_template_root = Path(_tpl).resolve() if _tpl else None
    _wips = bt_cfg.get("write_ips") or []
    if isinstance(_wips, list) and _wips:
        bt_write_ips = {str(x).strip() for x in _wips if str(x).strip()}
    if bt_layers:
        print(f"行为树 tab: {len(bt_layers)} 层已配置, template_root={bt_template_root}, write_ips={sorted(bt_write_ips)}")

    print(f"=" * 50)
    print(f"Debug Relay Server (multi-client)")
    print(f"  Port: {args.port}")
    print(f"  Host: {args.host}")
    print(f"  Source: {src_dir}")
    print(f"  Events: {events_dir}")
    print(f"  UI: http://{args.host}:{args.port}")
    print(f"  WS Game: ws://{args.host}:{args.port}/ws/game")
    print(f"  WS Browser: ws://{args.host}:{args.port}/ws/browser")
    print(f"  Clients API: http://{args.host}:{args.port}/api/clients")
    print(f"=" * 50)

    if not src_dir.exists():
        print(f"WARNING: source directory not exists: {src_dir}")
        print(f"  Source browsing will not work.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
