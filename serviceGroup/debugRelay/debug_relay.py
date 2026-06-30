#!/usr/bin/env python3
r"""
Debug Relay Server - 真机调试中继服务

功能：
- HTTP 服务：提供调试前端 UI
- WS 服务：同时接受游戏端和浏览器端连接，消息路由转发
- Console 全量同步：新连接获取历史消息
- 源文件读取：从项目目录读取源码

用法：
    python debug_relay.py --port 9229 --src "D:/Codlib/douque/xzmx/ClientEngineGame/trunk/assets"
"""

import os
import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime, date
from typing import Set

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except Exception:
    _HAS_YAML = False

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware
import uvicorn


# ---- Config ----

DEFAULT_PORT = 9229
# 默认扫描 assets 下的所有 .ts / .js 文件
DEFAULT_SRC = "../../../assets"


# 允许的文件扩展名（仅这些类型会被索引）
INDEXED_EXTS = [".ts", ".js"]

# 消息类型枚举
class MsgType:
    # Game -> Relay
    CONSOLE_LOG = "console_log"        # 控制台日志
    CONSOLE_WARN = "console_warn"
    CONSOLE_ERROR = "console_error"
    CONSOLE_INFO = "console_info"
    SOURCE_LIST = "source_list"         # 源文件列表响应
    SOURCE_CONTENT = "source_content"  # 源文件内容响应
    BREAKPOINT_HIT = "breakpoint_hit"  # 断点命中
    PAUSE_STATE = "pause_state"        # 暂停状态通知
    PERF_SNAPSHOT = "perf_snapshot"    # 性能指标快照
    PERF_MARK = "perf_mark"            # 业务段耗时 (mark/measure)
    RUNTIME_SOURCE = "runtime_source"  # 运行时源码（hot-patch 用）
    IMPORTANT_EVENT = "important_event"  # 重要事件（按日归档）

    # 场景节点树
    SCENE_TREE = "scene_tree"            # 场景树快照
    SCENE_NODE_INFO = "scene_node_info"  # 节点组件详情

    # Relay -> Game
    REGISTER_BREAKPOINT = "register_breakpoint"  # 注册断点
    REMOVE_BREAKPOINT = "remove_breakpoint"      # 移除断点
    RESUME = "resume"                  # 继续执行
    EVAL = "eval"                      # 执行表达式
    FETCH_RUNTIME_SOURCE = "fetch_runtime_source"  # 请求运行时源码
    RUNTIME_RELOAD = "runtime_reload"      # 刷新 Web preview runtime

    # Browser -> Game (场景控制)
    SCENE_GET_TREE = "scene_get_tree"        # 请求场景树
    SCENE_SET_ACTIVE = "scene_set_active"    # 设置节点显隐
    SCENE_GET_NODE_INFO = "scene_get_node_info"  # 请求节点详情
    SCENE_SET_PROPERTY = "scene_set_property"    # 修改节点/组件属性

    # Relay -> Browser
    CONSOLE_BATCH = "console_batch"    # 批量控制台消息（新连接时发送历史）
    GAME_CONNECTED = "game_connected"  # 游戏端连接通知
    GAME_DISCONNECTED = "game_disconnected"  # 游戏端断开通知


# ---- State ----

# 游戏端 WebSocket 连接
game_ws: WebSocket | None = None

# 游戏端是否已连接（独立于 game_ws 引用，用于新浏览器连接时查询状态）
game_connected: bool = False

# 浏览器端 WebSocket 连接集合
browser_ws_set: Set[WebSocket] = set()

# Console 消息缓冲（环形缓冲区，保持最近 1000 条）
console_buffer: list = []
CONSOLE_BUFFER_MAX = 50000
console_seq = 0  # 消息序号

# 性能快照环形缓冲区（最近 600 条 = 约 10 分钟 @ 1Hz）
perf_buffer: list = []
PERF_BUFFER_MAX = 600

# 源文件目录
src_dir: Path = None

# 重要事件存储目录（按日分割 JSONL 文件）
events_dir: Path = None

# IP 白名单(可选,未启用时允许所有 IP)
whitelist_enabled: bool = False
whitelist_ips: set = set()


# ---- IP Whitelist ----

async def _enforce_whitelist(websocket: WebSocket) -> bool:
    """白名单校验。返回 True=放行,False=已拒绝并 close。"""
    if not whitelist_enabled:
        return True
    client_ip = websocket.client.host if websocket.client else "<unknown>"
    if client_ip in whitelist_ips:
        return True
    # 拒绝的连接：打印 IP + 时间 + 端点路径，便于排查未授权访问
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
    每行一个 JSON 对象，字段: category, name, data, ts
    """
    if not events_dir:
        return

    category = msg.get("category", "unknown")
    # 清理 category 中的路径分隔符，防止目录穿越
    safe_category = category.replace("/", "_").replace("\\", "_").replace("..", "_")
    today = date.today().isoformat()  # YYYY-MM-DD

    day_dir = events_dir / safe_category
    day_dir.mkdir(parents=True, exist_ok=True)

    filepath = day_dir / f"{today}.jsonl"

    entry = {
        "category": category,
        "name": msg.get("name", ""),
        "data": msg.get("data", {}),
        "ts": msg.get("ts", datetime.now().isoformat()),
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
    """调试前端入口页面"""
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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "game_connected": game_ws is not None,
        "browser_count": len(browser_ws_set),
        "console_buffer_size": len(console_buffer),
    }


# ---- WebSocket Handling ----

async def handle_game_websocket(websocket: WebSocket):
    """处理游戏端连接"""
    if not await _enforce_whitelist(websocket):
        return

    global game_ws, game_connected, console_buffer, console_seq, perf_buffer

    # 游戏重连时清空旧缓冲，新会话重新累积
    console_buffer.clear()
    perf_buffer.clear()
    console_seq = 0

    await websocket.accept()
    game_ws = websocket
    game_connected = True

    # 通知所有浏览器：游戏端已连接 + 清空旧缓存重新同步
    await broadcast_to_browsers({
        "type": MsgType.GAME_CONNECTED,
        "ts": datetime.now().isoformat(),
        "clear_console": True,
    })

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            await handle_game_message(msg)
    except WebSocketDisconnect:
        pass
    finally:
        game_ws = None
        game_connected = False
        # 通知所有浏览器：游戏端已断开
        await broadcast_to_browsers({
            "type": MsgType.GAME_DISCONNECTED,
            "ts": datetime.now().isoformat(),
        })


async def handle_browser_websocket(websocket: WebSocket):
    """处理浏览器端连接"""
    if not await _enforce_whitelist(websocket):
        return

    await websocket.accept()
    browser_ws_set.add(websocket)

    # 新浏览器连接时：立即发送游戏端当前连接状态
    if game_connected:
        await websocket.send_json({
            "type": MsgType.GAME_CONNECTED,
            "ts": datetime.now().isoformat(),
        })
    else:
        await websocket.send_json({
            "type": MsgType.GAME_DISCONNECTED,
            "ts": datetime.now().isoformat(),
        })

    # 发送 console 历史
    if console_buffer:
        await websocket.send_json({
            "type": MsgType.CONSOLE_BATCH,
            "messages": console_buffer,
        })

    # 发送 perf 历史（最近 600 条）
    if perf_buffer:
        await websocket.send_json({
            "type": "perf_history",
            "snapshots": perf_buffer,
        })

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            await handle_browser_message(msg, websocket)
    except WebSocketDisconnect:
        pass
    finally:
        browser_ws_set.discard(websocket)


async def handle_game_message(msg: dict):
    """处理来自游戏端的消息"""
    global console_seq

    msg_type = msg.get("type")

    if msg_type in (MsgType.CONSOLE_LOG, MsgType.CONSOLE_WARN,
                    MsgType.CONSOLE_ERROR, MsgType.CONSOLE_INFO):
        # Console 消息：添加到缓冲区并转发给浏览器
        console_seq += 1
        entry = {
            "seq": console_seq,
            "type": msg_type,
            "content": msg.get("content", ""),
            "ts": msg.get("ts", datetime.now().isoformat()),
        }
        console_buffer.append(entry)
        # 环形缓冲区：超过上限时移除最早的
        if len(console_buffer) > CONSOLE_BUFFER_MAX:
            console_buffer.pop(0)

        # 转发给所有浏览器
        await broadcast_to_browsers(entry)

    elif msg_type == MsgType.SOURCE_LIST:
        # 源文件列表：直接转发给浏览器
        await broadcast_to_browsers(msg)

    elif msg_type == MsgType.SOURCE_CONTENT:
        # 源文件内容：直接转发给浏览器
        await broadcast_to_browsers(msg)

    elif msg_type == MsgType.BREAKPOINT_HIT:
        # 断点命中：通知所有浏览器暂停
        await broadcast_to_browsers(msg)

    elif msg_type == MsgType.PAUSE_STATE:
        # 暂停状态通知
        await broadcast_to_browsers(msg)

    elif msg_type == MsgType.PERF_SNAPSHOT:
        # 性能指标快照：只保留最近 600 条供新连接同步
        perf_buffer.append(msg)
        if len(perf_buffer) > PERF_BUFFER_MAX:
            perf_buffer.pop(0)
        # 调试：每 30 条打一次日志
        if len(perf_buffer) % 30 == 0:
            print(f"[debug-relay] perf_buffer size={len(perf_buffer)} browsers={len(browser_ws_set)} latest_fps={msg.get('fps')}")
        await broadcast_to_browsers(msg)

    elif msg_type == MsgType.PERF_MARK:
        # 业务段耗时：转发给浏览器（mark/measure 产生，低频无需缓冲）
        await broadcast_to_browsers(msg)

    elif msg_type == MsgType.RUNTIME_SOURCE:
        # 运行时源码：转发给浏览器（hot-patch 同步）
        await broadcast_to_browsers(msg)

    elif msg_type == MsgType.IMPORTANT_EVENT:
        # 重要事件：持久化到按日分割的 JSONL 文件 + 转发给浏览器
        persist_important_event(msg)
        await broadcast_to_browsers(msg)

    elif msg_type in (MsgType.SCENE_TREE, MsgType.SCENE_NODE_INFO):
        # 场景树/节点详情：直接转发给浏览器
        await broadcast_to_browsers(msg)

    # eval 结果：直接转发给浏览器（无 type 字段，靠 eval_result 判断）
    if "eval_result" in msg:
        await broadcast_to_browsers(msg)


async def handle_browser_message(msg: dict, sender: WebSocket):
    """处理来自浏览器的消息"""
    global game_ws

    msg_type = msg.get("type")

    if msg_type == MsgType.REGISTER_BREAKPOINT:
        # 注册断点：转发给游戏端
        if game_ws:
            await game_ws.send_json(msg)

    elif msg_type == MsgType.REMOVE_BREAKPOINT:
        # 移除断点：转发给游戏端
        if game_ws:
            await game_ws.send_json(msg)

    elif msg_type == MsgType.RESUME:
        # 继续执行：转发给游戏端
        if game_ws:
            await game_ws.send_json(msg)

    elif msg_type == MsgType.EVAL:
        # 执行表达式：转发给游戏端
        if game_ws:
            await game_ws.send_json(msg)

    elif msg_type == MsgType.RUNTIME_RELOAD:
        # 刷新 Web preview runtime：转发给游戏端
        if game_ws:
            await game_ws.send_json(msg)

    elif msg_type in (MsgType.SCENE_GET_TREE, MsgType.SCENE_SET_ACTIVE, MsgType.SCENE_GET_NODE_INFO, MsgType.SCENE_SET_PROPERTY):
        # 场景控制：转发给游戏端
        if game_ws:
            await game_ws.send_json(msg)


async def broadcast_to_browsers(msg: dict):
    """广播消息给所有浏览器客户端"""
    if not browser_ws_set:
        return

    msg_json = json.dumps(msg)
    # 逐个发送，移除断开的连接
    dead_ws = set()
    for ws in browser_ws_set:
        try:
            await ws.send_text(msg_json)
        except Exception:
            dead_ws.add(ws)

    for ws in dead_ws:
        browser_ws_set.discard(ws)


# ---- Source File API ----

@app.get("/api/sources")
async def list_sources():
    """列出所有可调试的源文件"""
    if not src_dir or not src_dir.exists():
        return {"files": [], "error": "src_dir not configured (run with --src)"}

    files = []
    for ext in INDEXED_EXTS:
        for f in src_dir.rglob(f"*{ext}"):
            # 跳过 .meta 文件和 node_modules 等
            if '.meta' in f.name or 'node_modules' in f.parts:
                continue
            rel = f.relative_to(src_dir)
            files.append(str(rel).replace("\\", "/"))

    return {"files": sorted(files)}


@app.get("/api/source")
async def get_source(path: str):
    """获取源文件内容"""
    if not src_dir or not src_dir.exists():
        return JSONResponse({"error": "src_dir not configured (run with --src)"}, status_code=500)

    # 安全检查：防止目录遍历（字符串替换，不能用 Path.replace）
    if ".." in path:
        return JSONResponse({"error": "invalid path: .. not allowed"}, status_code=403)

    # 将前向斜杠转为当前系统路径分隔符
    safe_path = path.replace("/", os.sep)
    full_path = src_dir / safe_path

    # 必须仍在 src_dir 内
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


# ---- Runtime Control API ----

@app.post("/api/runtime/reload")
async def reload_runtime():
    """刷新 Web preview runtime。

    Agent 可直接调用:
      curl -X POST http://host:5003/api/runtime/reload

    relay 转发 runtime_reload 给 /ws/game；Web preview 收到后执行 location.reload()。
    """
    if not game_ws:
        return JSONResponse({
            "ok": False,
            "error": "game not connected",
            "hint": "Open/refresh preview first, wait for game_connected=true",
        }, status_code=409)

    msg = {
        "type": MsgType.RUNTIME_RELOAD,
        "ts": datetime.now().isoformat(),
        "source": "http_api",
    }
    try:
        await game_ws.send_json(msg)
    except Exception as e:
        return JSONResponse({
            "ok": False,
            "error": f"send failed: {e}",
        }, status_code=500)

    return {
        "ok": True,
        "message": "runtime_reload sent to game",
        "ts": msg["ts"],
    }

# ---- Important Event Query API ----

@app.get("/api/events")
async def query_events(category: str = None, date: str = None, limit: int = 100):
    """查询按日归档的重要事件。

    参数:
      category: 事件分类 (如 "enter_room")，不传则返回所有分类
      date:     日期 (如 "2025-01-15")，不传则返回最近一天
      limit:    返回条数上限 (默认 100)

    返回:
      {events: [{category, name, data, ts}, ...], count, date, category}
    """
    if not events_dir or not events_dir.exists():
        return {"events": [], "count": 0, "date": date, "category": category,
                "error": "events_dir not configured (run with --events-dir)"}

    # 确定要扫描的目录
    if category:
        safe_category = category.replace("/", "_").replace("\\", "_").replace("..", "_")
        scan_dirs = [events_dir / safe_category]
    else:
        scan_dirs = [d for d in events_dir.iterdir() if d.is_dir()]

    # 确定 date
    # 注意:形参 date(str)遮蔽了 datetime.date,此处不能写 date.today()
    # 用 datetime.now().date() 取今天,绕开遮蔽
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
                entry["_idx"] = i  # 文件内原始行号，供删除定位
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
    """列出可查询的日期列表。

    参数:
      category: 事件分类，不传则列出所有分类
    """
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
            date_str = f.stem  # YYYY-MM-DD
            all_dates.append({"category": cat_name, "date": date_str})

    return {"dates": sorted(all_dates, key=lambda x: x["date"], reverse=True), "categories": sorted(categories)}


@app.delete("/api/events")
async def delete_event(category: str, date: str, index: int):
    """删除指定分类/日期下第 index 条事件记录（0-based，按文件原始顺序）。

    参数:
      category: 事件分类
      date:     日期 (YYYY-MM-DD)
      index:    要删除的行索引（0-based）

    返回:
      {ok, remaining, category, date}
    """
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

    # 移除目标行，写回文件
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
    """加载配置文件。按后缀解析: .yaml/.yml 走 PyYAML, .json 走 json。无匹配后缀先 json 再 yaml。"""
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
    # 未知后缀:先 json 再 yaml
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
    parser.add_argument("--src", default=DEFAULT_SRC, help="Source directory to serve")
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

    # 解析源文件目录（相对于当前文件）
    src_dir = Path(args.src).resolve()

    # 解析重要事件存储目录
    if args.events_dir:
        events_dir = Path(args.events_dir).resolve()
        events_dir.mkdir(parents=True, exist_ok=True)
    else:
        # 默认: 与 debug_relay.py 同级的 events/ 目录
        events_dir = Path(__file__).parent / "events"
        events_dir.mkdir(parents=True, exist_ok=True)

    # 解析 IP 白名单:CLI 显式值 > 配置文件
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

    print(f"=" * 50)
    print(f"Debug Relay Server")
    print(f"  Port: {args.port}")
    print(f"  Host: {args.host}")
    print(f"  Source: {src_dir}")
    print(f"  Events: {events_dir}")
    print(f"  UI: http://{args.host}:{args.port}")
    print(f"  WS Game: ws://{args.host}:{args.port}/ws/game")
    print(f"  WS Browser: ws://{args.host}:{args.port}/ws/browser")
    print(f"=" * 50)

    if not src_dir.exists():
        print(f"WARNING: source directory not exists: {src_dir}")
        print(f"  Source browsing will not work.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")