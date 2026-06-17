#!/usr/bin/env python3
r"""
Debug Relay Server - 真机调试中继服务

功能：
- HTTP 服务：提供调试前端 UI
- WS 服务：同时接受游戏端和浏览器端连接，消息路由转发
- Console 全量同步：新连接获取历史消息
- 源文件读取：从项目目录读取源码

用法：
    python debug_relay.py --port 9229 --src "D:/Codlib/douque/xzmx/ClientEngineGame/trunk/assets/game/scripts"
"""

import os
import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Set

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware
import uvicorn


# ---- Config ----

DEFAULT_PORT = 9229
DEFAULT_SRC = "../../../game/scripts"

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

    # Relay -> Game
    REGISTER_BREAKPOINT = "register_breakpoint"  # 注册断点
    REMOVE_BREAKPOINT = "remove_breakpoint"      # 移除断点
    RESUME = "resume"                  # 继续执行
    EVAL = "eval"                      # 执行表达式

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

# 源文件目录
src_dir: Path = None


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
    global game_ws, game_connected, console_buffer, console_seq

    # 游戏重连时清空旧缓冲，新会话重新累积
    console_buffer.clear()
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
    for ext in [".ts", ".js"]:
        for f in src_dir.rglob(f"*{ext}"):
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


# ---- WebSocket Routes ----

@app.websocket("/ws/game")
async def ws_game(websocket: WebSocket):
    await handle_game_websocket(websocket)


@app.websocket("/ws/browser")
async def ws_browser(websocket: WebSocket):
    await handle_browser_websocket(websocket)


# ---- CLI ----

def parse_args():
    parser = argparse.ArgumentParser(description="Debug Relay Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--src", default=DEFAULT_SRC, help="Source directory to serve")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # 解析源文件目录（相对于当前文件）
    src_dir = Path(args.src).resolve()

    print(f"=" * 50)
    print(f"Debug Relay Server")
    print(f"  Port: {args.port}")
    print(f"  Host: {args.host}")
    print(f"  Source: {src_dir}")
    print(f"  UI: http://{args.host}:{args.port}")
    print(f"  WS Game: ws://{args.host}:{args.port}/ws/game")
    print(f"  WS Browser: ws://{args.host}:{args.port}/ws/browser")
    print(f"=" * 50)

    if not src_dir.exists():
        print(f"WARNING: source directory not exists: {src_dir}")
        print(f"  Source browsing will not work.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")