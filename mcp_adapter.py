#!/usr/bin/env python3
"""
Cocos MCP Adapter — stdio MCP server that proxies to CocosCreator's internal MCP.

This adapter:
1. Exposes management tools (cocos_start/stop/status/restart) via InfoServer REST API
2. Dynamically discovers and proxies all tools from CocosCreator's internal MCP server
3. Returns friendly errors when CocosCreator is not running

Usage:
    python mcp_adapter.py

Register in opencode.json:
    "cocos": {
        "type": "local",
        "command": ["python", "mcp_adapter.py"],
        "enabled": true
    }
"""

import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

# InfoServer REST API base URL
INFOSERVER_URL = "http://127.0.0.1:5001"
SERVICE_NAME = "cocos-creator"

# Global state
_app = Server("cocos-mcp-adapter")
_proxy_tools: Dict[str, Dict[str, Any]] = {}  # name -> tool schema
_proxy_tools_loaded = False


# ── HTTP helpers ────────────────────────────────────────────────────────────

async def _get(path: str, timeout: float = 10.0) -> Dict[str, Any]:
    """GET request to InfoServer."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{INFOSERVER_URL}{path}")
        return resp.json()


async def _post(path: str, data: Optional[Dict] = None, timeout: float = 30.0) -> Dict[str, Any]:
    """POST request to InfoServer."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{INFOSERVER_URL}{path}", json=data or {})
        return resp.json()


# ── Management tools ────────────────────────────────────────────────────────

async def _cocos_start() -> Dict[str, Any]:
    """Start CocosCreator and wait for internal MCP to be ready."""
    global _proxy_tools_loaded

    # Start the service via InfoServer
    result = await _post(f"/api/services/{SERVICE_NAME}/start")

    if result.get("status") != "ok":
        return {"success": False, "error": f"Failed to start: {result}"}

    # Wait for internal MCP to become ready
    max_wait = 60
    for i in range(max_wait):
        await asyncio.sleep(1)
        health = await _get("/api/cocos-mcp/health", timeout=3.0)
        if health.get("reachable"):
            # Load proxy tools
            await _load_proxy_tools()
            return {
                "success": True,
                "message": "CocosCreator started and MCP server is ready",
                "service": result.get("service", {}),
                "tools_loaded": len(_proxy_tools),
            }

    return {
        "success": False,
        "error": f"CocosCreator started but MCP server not ready after {max_wait}s",
        "service": result.get("service", {}),
    }


async def _cocos_stop() -> Dict[str, Any]:
    """Stop CocosCreator."""
    global _proxy_tools_loaded, _proxy_tools

    result = await _post(f"/api/services/{SERVICE_NAME}/stop")
    _proxy_tools = {}
    _proxy_tools_loaded = False

    return {
        "success": result.get("status") == "ok",
        "service": result.get("service", {}),
    }


async def _cocos_status() -> Dict[str, Any]:
    """Get CocosCreator service status."""
    services = await _get("/api/services")
    for svc in services.get("services", []):
        if svc.get("name") == SERVICE_NAME:
            # Also check MCP health
            mcp_health = await _get("/api/cocos-mcp/health", timeout=3.0)
            return {
                "service": svc,
                "mcp_reachable": mcp_health.get("reachable", False),
                "proxy_tools_loaded": len(_proxy_tools),
            }
    return {"error": f"Service '{SERVICE_NAME}' not found"}


async def _cocos_restart() -> Dict[str, Any]:
    """Restart CocosCreator (stop then start)."""
    stop_result = await _cocos_stop()
    if not stop_result.get("success"):
        return {"success": False, "error": "Failed to stop", "stop_result": stop_result}

    await asyncio.sleep(2)  # Brief pause between stop and start
    return await _cocos_start()


async def _cocos_reload_preview() -> Dict[str, Any]:
    """Atomic: refresh assets + soft-reload scene + reload preview runtime.

    一键同步业务代码改动到 preview 运行时（含 plugin 重载）。
    后端走 infoServer /api/cocos-mcp/reload 聚合三个原子操作。
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{INFOSERVER_URL}/api/cocos-mcp/reload")
            data = resp.json()
            return {
                "success": data.get("ok", False),
                "steps": data.get("steps", []),
                "relay": data.get("relay"),
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Proxy tool management ───────────────────────────────────────────────────

async def _load_proxy_tools() -> bool:
    """Load tool list from CocosCreator's internal MCP via InfoServer proxy."""
    global _proxy_tools, _proxy_tools_loaded

    try:
        result = await _get("/api/cocos-mcp/tools", timeout=10.0)
        tools = result.get("tools", [])
        _proxy_tools = {t["name"]: t for t in tools}
        _proxy_tools_loaded = True
        return True
    except Exception as e:
        print(f"[cocos-adapter] Failed to load proxy tools: {e}", file=sys.stderr)
        return False


async def _call_proxy_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call a tool on CocosCreator's internal MCP via InfoServer proxy."""
    if not _proxy_tools_loaded or tool_name not in _proxy_tools:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Tool '{tool_name}' not available. CocosCreator may not be running. Call cocos_start first."}],
        }

    # Build JSON-RPC request
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    try:
        result = await _post("/api/cocos-mcp/call", data=payload, timeout=30.0)
        return result
    except Exception as e:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Error calling tool: {e}"}],
        }


# ── MCP Server handlers ─────────────────────────────────────────────────────

@_app.list_tools()
async def list_tools() -> List[Tool]:
    """Return all available tools (management + proxy)."""
    tools = [
        # Management tools
        Tool(
            name="cocos_start",
            description="Start CocosCreator editor and wait for its internal MCP server to be ready. Call this before using any cocos_mcp_* tools.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_stop",
            description="Stop CocosCreator editor process.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_status",
            description="Get CocosCreator service status and MCP server health.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_restart",
            description="Restart CocosCreator editor (stop then start).",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_reload_preview",
            description="Atomic: refresh_assets + soft_reload_scene + reload preview runtime. Sync business code (including plugin) to preview runtime in one call. Use after editing TS/JS in assets/.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]

    # Add proxy tools (prefixed to avoid conflicts)
    for name, schema in _proxy_tools.items():
        tools.append(Tool(
            name=f"cocos_mcp_{name}",
            description=f"[Proxy] {schema.get('description', 'CocosCreator MCP tool')}",
            inputSchema=schema.get("inputSchema", {"type": "object", "properties": {}}),
        ))

    return tools


@_app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    # Management tools
    if name == "cocos_start":
        result = await _cocos_start()
    elif name == "cocos_stop":
        result = await _cocos_stop()
    elif name == "cocos_status":
        result = await _cocos_status()
    elif name == "cocos_restart":
        result = await _cocos_restart()
    elif name == "cocos_reload_preview":
        result = await _cocos_reload_preview()
    # Proxy tools (strip prefix)
    elif name.startswith("cocos_mcp_"):
        tool_name = name[len("cocos_mcp_"):]
        result = await _call_proxy_tool(tool_name, arguments)
    else:
        result = {"error": f"Unknown tool: {name}"}

    # Format result as text
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


# ── Main ────────────────────────────────────────────────────────────────────

async def main():
    """Run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await _app.run(
            read_stream,
            write_stream,
            _app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
