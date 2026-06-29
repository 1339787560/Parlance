#!/usr/bin/env python3
"""
Cocos MCP Adapter — stdio MCP server，CocosCreator 编辑器操作的精简入口。

设计：
- 固定暴露核心工具 + 节点操作封装 + 通用入口（cocos_raw_tool）
- cocos_status 检测三维度：进程/7456端口/3000端口
- cocos_start 启动 CocosCreator 并等待 MCP 就绪（最多 60s）
- 节点操作封装统一参数命名（nodeUuid），屏蔽底层 node-tools(uuid) / component-tools(nodeUuid) 不一致
- cocos_set_component_property 自动推断 propertyType，免去手动指定
- cocos_raw_tool 用于访问非核心的底层 MCP 工具

底层经 InfoServer REST API 转发到 CocosCreator 内部 MCP（:3000）。

Usage:
    python mcp_adapter.py
"""

import asyncio
import json
import subprocess
from typing import Any, Dict, List

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)

# InfoServer REST API base URL
INFOSERVER_URL = "http://127.0.0.1:5001"

# Global state
_app = Server("cocos-mcp-adapter")

_NOT_RUNNING_HINT = (
    "CocosCreator 未启动或 MCP 不可达。"
    "请先启动 CocosCreator 编辑器并确认 cocos-mcp-server 扩展已加载"
    "（autoStart=false 需在编辑器面板手动启动）。"
)


# ── HTTP helpers ────────────────────────────────────────────────────────────

async def _get(path: str, timeout: float = 10.0) -> Dict[str, Any]:
    """GET request to InfoServer."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{INFOSERVER_URL}{path}")
        return resp.json()


async def _post(path: str, data: Any = None, timeout: float = 30.0) -> Any:
    """POST request to InfoServer. Returns parsed JSON or raw response."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{INFOSERVER_URL}{path}", json=data or {})
        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}


# ── Health check ────────────────────────────────────────────────────────────

async def _detect_cocos_status() -> Dict[str, Any]:
    """检测 CocosCreator 状态，返回详细信息。
    
    检测三个维度：
    1. CocosCreator 进程是否存在（pgrep）
    2. 7456 端口是否监听（preview）
    3. 3000 端口 MCP 服务是否可达
    
    返回：
    {
        "cocos_running": bool,      # CocosCreator 进程是否存在
        "preview_port": bool,       # 7456 端口是否监听
        "mcp_service": bool,        # 3000 端口 MCP 服务是否可达
        "ready": bool,              # 是否就绪（MCP 可达）
        "hint": str                 # 提示信息
    }
    """
    status = {
        "cocos_running": False,
        "preview_port": False,
        "mcp_service": False,
        "ready": False,
        "hint": ""
    }
    
    # 1. 检查 CocosCreator 进程
    try:
        result = subprocess.run(
            ["pgrep", "-f", "CocosCreator"],
            capture_output=True, text=True, timeout=2
        )
        status["cocos_running"] = result.returncode == 0
    except Exception:
        pass
    
    # 2. 检查 7456 端口（preview）
    try:
        result = subprocess.run(
            ["lsof", "-i", ":7456", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=2
        )
        # lsof 输出会截断进程名，CocosCreator 显示为 CocosCrea
        status["preview_port"] = "CocosCrea" in result.stdout
    except Exception:
        pass
    
    # 3. 检查 3000 端口（MCP 服务）
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://127.0.0.1:3000/health")
            status["mcp_service"] = resp.status_code == 200
    except Exception:
        pass
    
    # 4. 判断就绪状态
    status["ready"] = status["mcp_service"]
    
    # 5. 生成提示
    if status["ready"]:
        status["hint"] = "CocosCreator 已启动，MCP 服务就绪"
    elif status["cocos_running"]:
        status["hint"] = "CocosCreator 已启动，但 MCP 服务未就绪。请在编辑器中启动 MCP 扩展"
    else:
        status["hint"] = "CocosCreator 未启动。调用 cocos_start 启动"
    
    return status


async def _ensure_cocos_running() -> bool:
    """检查 CocosCreator MCP 是否可达。返回 True/False。"""
    status = await _detect_cocos_status()
    return status["ready"]


async def _cocos_start() -> Dict[str, Any]:
    """启动 CocosCreator 并等待 MCP 服务就绪。
    
    调用 infoServer 的 /api/services/cocos-creator/start，
    然后轮询等待 MCP 服务就绪（最多 60s）。
    """
    # 先检查是否已经就绪
    status = await _detect_cocos_status()
    if status["ready"]:
        return {
            "success": True,
            "message": "CocosCreator 已启动，MCP 服务就绪",
            "status": status
        }
    
    # 调用 infoServer 启动 CocosCreator
    try:
        result = await _post("/api/services/cocos-creator/start", data={}, timeout=10.0)
        if result.get("status") != "ok":
            return {
                "success": False,
                "error": f"启动失败: {result}",
                "status": status
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"调用 infoServer 失败: {e}",
            "status": status
        }
    
    # 等待 MCP 服务就绪（最多 60s）
    max_wait = 60
    for i in range(max_wait):
        await asyncio.sleep(1)
        status = await _detect_cocos_status()
        if status["ready"]:
            return {
                "success": True,
                "message": f"CocosCreator 启动成功，MCP 服务就绪（等待 {i+1}s）",
                "status": status
            }
    
    return {
        "success": False,
        "error": f"CocosCreator 已启动，但 MCP 服务未在 {max_wait}s 内就绪",
        "status": status
    }


async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Forward a tools/call JSON-RPC request to CocosCreator internal MCP.

    Precondition: caller must ensure CocosCreator is running.
    """
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
        return await _post("/api/cocos-mcp/call", data=payload, timeout=30.0)
    except Exception as e:
        return {"isError": True, "error": str(e)}


# ── Core tool implementations ────────────────────────────────────────────────

async def _cocos_status() -> Dict[str, Any]:
    """检查 CocosCreator 状态。返回详细信息。"""
    return await _detect_cocos_status()


async def _cocos_reload_preview() -> Dict[str, Any]:
    """Atomic: refresh_assets + soft_reload_scene + reload preview runtime."""
    try:
        data = await _post("/api/cocos-mcp/reload", data={}, timeout=30.0)
        return {
            "success": data.get("ok", False) if isinstance(data, dict) else False,
            "steps": data.get("steps", []) if isinstance(data, dict) else [],
            "relay": data.get("relay") if isinstance(data, dict) else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _cocos_refresh_assets() -> Dict[str, Any]:
    """Call project_refresh_assets on CocosCreator internal MCP."""
    return await _call_mcp_tool("project_refresh_assets", {})


async def _cocos_soft_reload_scene() -> Dict[str, Any]:
    """Call sceneAdvanced_soft_reload_scene on CocosCreator internal MCP."""
    return await _call_mcp_tool("sceneAdvanced_soft_reload_scene", {})


async def _cocos_get_console_logs() -> Dict[str, Any]:
    """Call debug_get_console_logs on CocosCreator internal MCP."""
    return await _call_mcp_tool("debug_get_console_logs", {})


async def _cocos_get_editor_info() -> Dict[str, Any]:
    """Call debug_get_editor_info on CocosCreator internal MCP."""
    return await _call_mcp_tool("debug_get_editor_info", {})


async def _cocos_execute_scene_script(name: str, method: str, args: List[Any]) -> Dict[str, Any]:
    """Call sceneAdvanced_execute_scene_script on CocosCreator internal MCP."""
    arguments: Dict[str, Any] = {"name": name, "method": method}
    if args:
        arguments["args"] = args
    return await _call_mcp_tool("sceneAdvanced_execute_scene_script", arguments)


async def _cocos_raw_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Generic entry: call any tool on CocosCreator internal MCP by name."""
    return await _call_mcp_tool(tool_name, arguments)


# ── Node operation wrappers (统一参数命名，屏蔽底层不一致) ──────────────────
# 底层 node-tools.ts 用 `uuid`，component-tools.ts 用 `nodeUuid`，这里统一为 `nodeUuid`

async def _cocos_find_node(name: str) -> Dict[str, Any]:
    """查找节点：按名称查找，返回 UUID 和基本信息。底层 node_find_node_by_name。"""
    return await _call_mcp_tool("node_find_node_by_name", {"name": name})


async def _cocos_get_node_info(nodeUuid: str) -> Dict[str, Any]:
    """获取节点信息：位置/旋转/缩放/子节点/组件。底层 node_get_node_info（uuid → nodeUuid 统一）。"""
    return await _call_mcp_tool("node_get_node_info", {"uuid": nodeUuid})


async def _cocos_create_node(name: str, parentUuid: str = "", components: List[str] = None) -> Dict[str, Any]:
    """创建节点：统一 name 参数（底层也用 name，但执行时曾丢失），可选 parentUuid 和 components。
    底层 node_create_node。"""
    arguments: Dict[str, Any] = {"name": name}
    if parentUuid:
        arguments["parentUuid"] = parentUuid
    if components:
        arguments["components"] = components
    return await _call_mcp_tool("node_create_node", arguments)


async def _cocos_add_component(nodeUuid: str, componentType: str) -> Dict[str, Any]:
    """添加组件：统一 nodeUuid + componentType。底层 component_add_component（参数已一致）。"""
    return await _call_mcp_tool("component_add_component", {"nodeUuid": nodeUuid, "componentType": componentType})


async def _cocos_set_component_property(
    nodeUuid: str, componentType: str, property: str, value: Any, propertyType: str = ""
) -> Dict[str, Any]:
    """设置组件属性：统一 nodeUuid + componentType + property + value + propertyType。
    底层 component_set_component_property（参数已一致，但 propertyType 必填，这里自动推断）。"""
    arguments: Dict[str, Any] = {
        "nodeUuid": nodeUuid,
        "componentType": componentType,
        "property": property,
        "value": value,
    }
    if propertyType:
        arguments["propertyType"] = propertyType
    else:
        # 自动推断类型
        if isinstance(value, str):
            arguments["propertyType"] = "string"
        elif isinstance(value, bool):
            arguments["propertyType"] = "boolean"
        elif isinstance(value, (int, float)):
            arguments["propertyType"] = "number"
        elif isinstance(value, dict):
            if "width" in value and "height" in value:
                arguments["propertyType"] = "size"
            elif "x" in value and "y" in value:
                arguments["propertyType"] = "vec2"
            elif "r" in value and "g" in value:
                arguments["propertyType"] = "color"
            else:
                arguments["propertyType"] = "string"
        else:
            arguments["propertyType"] = "string"
    return await _call_mcp_tool("component_set_component_property", arguments)


# ── Tool schemas ─────────────────────────────────────────────────────────────

def _tool_schemas() -> List[Tool]:
    """Fixed tool list exposed to agent."""
    return [
        Tool(
            name="cocos_status",
            description=(
                "检查 CocosCreator 状态。"
                "检测三个维度：进程是否存在、7456 端口（preview）、3000 端口（MCP 服务）。"
                "返回 {cocos_running, preview_port, mcp_service, ready, hint}。"
                "无需 CocosCreator 已启动即可调用。"
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_start",
            description=(
                "启动 CocosCreator 并等待 MCP 服务就绪。"
                "调用 infoServer 启动 CocosCreator，然后轮询等待 MCP 服务就绪（最多 60s）。"
                "如果已就绪，直接返回成功。"
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_reload_preview",
            description=(
                "★ 最常用：一键同步业务代码改动到 preview 运行时。"
                "内部链路：refresh_assets → soft_reload_scene → runtime_reload。"
                "改完 assets/ 下的 TS/JS 代码后必须调用。"
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_refresh_assets",
            description=(
                "单独刷新资源（project_refresh_assets）。"
                "通常用 cocos_reload_preview 一键完成，仅在需单独刷新资源时使用。"
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_soft_reload_scene",
            description=(
                "单独软重载场景（sceneAdvanced_soft_reload_scene）。"
                "通常用 cocos_reload_preview 一键完成，仅在需单独重载场景脚本时使用。"
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_get_console_logs",
            description="获取 CocosCreator 编辑器的 console 日志（debug_get_console_logs）。",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_get_editor_info",
            description="获取 CocosCreator 编辑器信息（debug_get_editor_info），含版本、场景等。",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="cocos_execute_scene_script",
            description=(
                "执行场景脚本（sceneAdvanced_execute_scene_script）。"
                "用于在编辑器态触发场景脚本方法。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "场景脚本名称",
                    },
                    "method": {
                        "type": "string",
                        "description": "要调用的方法名",
                    },
                    "args": {
                        "type": "array",
                        "description": "方法参数（可选）",
                        "items": {},
                    },
                },
                "required": ["name", "method"],
            },
        ),
        Tool(
            name="cocos_find_node",
            description="按名称查找节点，返回 UUID 和基本信息。底层 find_node_by_name。",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "节点名称"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="cocos_get_node_info",
            description="获取节点信息：位置/旋转/缩放/子节点/组件。底层 get_node_info。",
            inputSchema={
                "type": "object",
                "properties": {
                    "nodeUuid": {"type": "string", "description": "节点 UUID"},
                },
                "required": ["nodeUuid"],
            },
        ),
        Tool(
            name="cocos_create_node",
            description="创建节点。底层 create_node。统一参数：name（必填）、parentUuid（可选）、components（可选，如 [\"cc.Sprite\", \"cc.Button\"]）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "节点名称"},
                    "parentUuid": {"type": "string", "description": "父节点 UUID（可选，不传则创建在场景根）"},
                    "components": {"type": "array", "items": {"type": "string"}, "description": "要添加的组件列表（可选，如 [\"cc.Sprite\", \"cc.Button\"]）"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="cocos_add_component",
            description="给节点添加组件。底层 add_component。统一参数：nodeUuid + componentType。",
            inputSchema={
                "type": "object",
                "properties": {
                    "nodeUuid": {"type": "string", "description": "节点 UUID"},
                    "componentType": {"type": "string", "description": "组件类型，如 cc.Sprite / cc.Label / cc.Button"},
                },
                "required": ["nodeUuid", "componentType"],
            },
        ),
        Tool(
            name="cocos_set_component_property",
            description="设置组件属性。底层 set_component_property。统一参数：nodeUuid + componentType + property + value + propertyType（可选，不传自动推断）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "nodeUuid": {"type": "string", "description": "节点 UUID"},
                    "componentType": {"type": "string", "description": "组件类型，如 cc.Label"},
                    "property": {"type": "string", "description": "属性名，如 string / fontSize / contentSize"},
                    "value": {"description": "属性值"},
                    "propertyType": {"type": "string", "description": "属性类型（可选，不传自动推断）。可选值：string/number/boolean/color/vec2/vec3/size"},
                },
                "required": ["nodeUuid", "componentType", "property", "value"],
            },
        ),
        Tool(
            name="cocos_raw_tool",
            description=(
                "通用入口：按工具名调用 CocosCreator 内部 MCP 的任意工具。"
                "用于访问 7 个核心工具未覆盖的底层功能。"
                "调用前会检查 CocosCreator 是否运行。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "底层 MCP 工具名，如 'node_get_node_info'",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "工具参数（可选，默认空对象）",
                        "additionalProperties": True,
                    },
                },
                "required": ["tool_name"],
            },
        ),
    ]


# ── MCP Server handlers ─────────────────────────────────────────────────────

@_app.list_tools()
async def list_tools() -> List[Tool]:
    """Return fixed tool set (core + node wrappers + raw_tool)."""
    return _tool_schemas()


@_app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    args = arguments or {}

    # ── Tools that don't require CocosCreator running ──
    if name == "cocos_status":
        result = await _cocos_status()
    elif name == "cocos_start":
        result = await _cocos_start()

    # ── reload_preview: the reload chain handles its own errors ──
    elif name == "cocos_reload_preview":
        result = await _cocos_reload_preview()

    # ── Tools that require CocosCreator running ──
    else:
        running = await _ensure_cocos_running()
        if not running:
            result = {"error": _NOT_RUNNING_HINT}
        elif name == "cocos_refresh_assets":
            result = await _cocos_refresh_assets()
        elif name == "cocos_soft_reload_scene":
            result = await _cocos_soft_reload_scene()
        elif name == "cocos_get_console_logs":
            result = await _cocos_get_console_logs()
        elif name == "cocos_get_editor_info":
            result = await _cocos_get_editor_info()
        elif name == "cocos_execute_scene_script":
            result = await _cocos_execute_scene_script(
                name=args["name"],
                method=args["method"],
                args=args.get("args", []),
            )
        elif name == "cocos_find_node":
            result = await _cocos_find_node(name=args["name"])
        elif name == "cocos_get_node_info":
            result = await _cocos_get_node_info(nodeUuid=args["nodeUuid"])
        elif name == "cocos_create_node":
            result = await _cocos_create_node(
                name=args["name"],
                parentUuid=args.get("parentUuid", ""),
                components=args.get("components"),
            )
        elif name == "cocos_add_component":
            result = await _cocos_add_component(
                nodeUuid=args["nodeUuid"],
                componentType=args["componentType"],
            )
        elif name == "cocos_set_component_property":
            result = await _cocos_set_component_property(
                nodeUuid=args["nodeUuid"],
                componentType=args["componentType"],
                property=args["property"],
                value=args["value"],
                propertyType=args.get("propertyType", ""),
            )
        elif name == "cocos_raw_tool":
            result = await _cocos_raw_tool(
                tool_name=args["tool_name"],
                arguments=args.get("arguments", {}),
            )
        else:
            result = {"error": f"Unknown tool: {name}"}

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
    import asyncio
    asyncio.run(main())
