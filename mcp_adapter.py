#!/usr/bin/env python3
"""
Cocos MCP Adapter — stdio MCP server，CocosCreator 编辑器操作的精简入口。

设计：
- 固定暴露核心工具 + 节点/组件/Prefab 封装 + 通用入口（cocos_raw_tool）
- cocos_status 检测三维度：进程/7456端口/3000端口（全部跨平台，不依赖 lsof/pgrep）
- cocos_start 启动 CocosCreator 并等待 MCP 就绪（最多 60s）
- 节点操作封装统一参数命名（nodeUuid），屏蔽底层 node-tools(uuid) / component-tools(nodeUuid) 不一致
- cocos_set_component_property 自动推断 propertyType，免去手动指定
- cocos_prefab_* 封装 prefab 加载/校验/挂脚本/保存等常用操作
- cocos_raw_tool 用于访问非核心的底层 MCP 工具

底层经 InfoServer REST API 转发到 CocosCreator 内部 MCP（:3000）。

Usage:
    python mcp_adapter.py
"""

import asyncio
import json
import socket
import subprocess
import sys
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

def _check_port_listening(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """跨平台检测端口是否监听。用 socket 连接试探，不依赖 lsof/netstat。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _check_process_running(name: str) -> bool:
    """跨平台检测进程是否在运行。

    Windows: tasklist /FO CSV /NH 子串匹配
    POSIX:   优先 pgrep，缺失则回退 ps
    """
    name_l = name.lower()
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                timeout=5, text=True, errors="ignore",
            )
            return any(name_l in line.lower() for line in out.splitlines())
        except Exception:
            return False
    try:
        r = subprocess.run(
            ["pgrep", "-if", name],
            capture_output=True, text=True, timeout=2,
        )
        return r.returncode == 0
    except FileNotFoundError:
        # 无 pgrep（部分精简环境）→ 回退 ps
        try:
            out = subprocess.check_output(
                ["ps", "-ax", "-o", "comm="],
                timeout=5, text=True, errors="ignore",
            )
            return any(name_l in line.lower() for line in out.splitlines())
        except Exception:
            return False
    except Exception:
        return False


async def _detect_cocos_status() -> Dict[str, Any]:
    """检测 CocosCreator 状态，返回详细信息。

    检测三个维度（全部跨平台，不依赖 lsof/pgrep 等平台命令）：
    1. CocosCreator 进程是否存在（win: tasklist / mac: pgrep+ps 回退）
    2. 7456 端口是否监听（preview）— socket 连接试探
    3. 3000 端口 MCP 服务是否可达 — HTTP /health

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
    status["cocos_running"] = _check_process_running("CocosCreator")

    # 2. 检查 7456 端口（preview）— socket 连接试探
    status["preview_port"] = _check_port_listening(7456)

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


# ── Prefab 操作封装 ─────────────────────────────────────────────────────────
# 薄封装，统一参数命名（prefabPath 用 db:// 协议路径），底层 prefab_* 系列。
# 给 agent 暴露常用 prefab 操作；其余可经 cocos_raw_tool 调用。

async def _cocos_prefab_list(folder: str = "db://assets") -> Dict[str, Any]:
    """列出项目内 prefab。底层 prefab_get_prefab_list。"""
    return await _call_mcp_tool("prefab_get_prefab_list", {"folder": folder})


async def _cocos_prefab_load(prefabPath: str) -> Dict[str, Any]:
    """加载 prefab（编辑器态打开）。底层 prefab_load_prefab。返回含根节点 UUID。"""
    return await _call_mcp_tool("prefab_load_prefab", {"prefabPath": prefabPath})


async def _cocos_prefab_info(prefabPath: str) -> Dict[str, Any]:
    """获取 prefab 详细信息。底层 prefab_get_prefab_info。"""
    return await _call_mcp_tool("prefab_get_prefab_info", {"prefabPath": prefabPath})


async def _cocos_prefab_validate(prefabPath: str) -> Dict[str, Any]:
    """校验 prefab 文件格式。底层 prefab_validate_prefab。"""
    return await _call_mcp_tool("prefab_validate_prefab", {"prefabPath": prefabPath})


async def _cocos_prefab_save(prefabPath: str, nodeUuid: str) -> Dict[str, Any]:
    """把节点改动回写为 prefab。底层 prefab_update_prefab。"""
    return await _call_mcp_tool("prefab_update_prefab", {"prefabPath": prefabPath, "nodeUuid": nodeUuid})


async def _cocos_prefab_instantiate(prefabPath: str, parentUuid: str = "", position: Dict[str, float] = None) -> Dict[str, Any]:
    """在场景实例化 prefab。底层 prefab_instantiate_prefab。"""
    arguments: Dict[str, Any] = {"prefabPath": prefabPath}
    if parentUuid:
        arguments["parentUuid"] = parentUuid
    if position:
        arguments["position"] = position
    return await _call_mcp_tool("prefab_instantiate_prefab", arguments)


async def _cocos_prefab_create(nodeUuid: str, savePath: str, prefabName: str) -> Dict[str, Any]:
    """从场景节点创建 prefab。底层 prefab_create_prefab。"""
    return await _call_mcp_tool("prefab_create_prefab", {
        "nodeUuid": nodeUuid,
        "savePath": savePath,
        "prefabName": prefabName,
    })


async def _cocos_prefab_duplicate(sourcePrefabPath: str, targetPrefabPath: str, newPrefabName: str = "") -> Dict[str, Any]:
    """复制 prefab。底层 prefab_duplicate_prefab。"""
    arguments: Dict[str, Any] = {
        "sourcePrefabPath": sourcePrefabPath,
        "targetPrefabPath": targetPrefabPath,
    }
    if newPrefabName:
        arguments["newPrefabName"] = newPrefabName
    return await _call_mcp_tool("prefab_duplicate_prefab", arguments)


async def _cocos_prefab_revert(nodeUuid: str) -> Dict[str, Any]:
    """把 prefab 实例还原为原始。底层 prefab_revert_prefab。"""
    return await _call_mcp_tool("prefab_revert_prefab", {"nodeUuid": nodeUuid})


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


async def _cocos_attach_script(nodeUuid: str, scriptPath: str) -> Dict[str, Any]:
    """给节点挂脚本组件：统一 nodeUuid + scriptPath。底层 component_attach_script。"""
    return await _call_mcp_tool("component_attach_script", {"nodeUuid": nodeUuid, "scriptPath": scriptPath})


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
            # hex 颜色字符串(#RRGGBB / #RRGGBBAA)推断为 color,否则 string
            if value.startswith("#") and len(value) in (7, 9) and all(c in "0123456789abcdefABCDEF" for c in value[1:]):
                arguments["propertyType"] = "color"
            else:
                arguments["propertyType"] = "string"
        elif isinstance(value, bool):
            arguments["propertyType"] = "boolean"
        elif isinstance(value, (int, float)):
            arguments["propertyType"] = "number"
        elif isinstance(value, dict):
            if "width" in value and "height" in value:
                arguments["propertyType"] = "size"
            elif "x" in value and "y" in value and "z" in value:
                arguments["propertyType"] = "vec3"
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
        # ── Prefab 操作封装 ──
        Tool(
            name="cocos_prefab_list",
            description="列出项目内 prefab。底层 prefab_get_prefab_list。",
            inputSchema={
                "type": "object",
                "properties": {
                    "folder": {"type": "string", "description": "文件夹路径（可选，默认 db://assets）", "default": "db://assets"},
                },
                "required": [],
            },
        ),
        Tool(
            name="cocos_prefab_load",
            description="加载（编辑器态打开）prefab，返回含根节点 UUID。底层 prefab_load_prefab。挂脚本/改属性前先 load 拿 nodeUuid。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prefabPath": {"type": "string", "description": "prefab 资源路径，如 db://assets/plugins/debug/prefabs/DebugView.prefab"},
                },
                "required": ["prefabPath"],
            },
        ),
        Tool(
            name="cocos_prefab_info",
            description="获取 prefab 详细信息。底层 prefab_get_prefab_info。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prefabPath": {"type": "string", "description": "prefab 资源路径"},
                },
                "required": ["prefabPath"],
            },
        ),
        Tool(
            name="cocos_prefab_validate",
            description="校验 prefab 文件格式。底层 prefab_validate_prefab。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prefabPath": {"type": "string", "description": "prefab 资源路径"},
                },
                "required": ["prefabPath"],
            },
        ),
        Tool(
            name="cocos_prefab_save",
            description="把节点改动回写为 prefab（保存）。底层 prefab_update_prefab。改完 prefab 后必须 save 才落盘。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prefabPath": {"type": "string", "description": "prefab 资源路径"},
                    "nodeUuid": {"type": "string", "description": "改动的节点 UUID（load 返回的根节点）"},
                },
                "required": ["prefabPath", "nodeUuid"],
            },
        ),
        Tool(
            name="cocos_prefab_instantiate",
            description="在场景实例化 prefab。底层 prefab_instantiate_prefab。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prefabPath": {"type": "string", "description": "prefab 资源路径"},
                    "parentUuid": {"type": "string", "description": "父节点 UUID（可选）"},
                    "position": {
                        "type": "object",
                        "description": "初始位置（可选）",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "z": {"type": "number"},
                        },
                    },
                },
                "required": ["prefabPath"],
            },
        ),
        Tool(
            name="cocos_prefab_create",
            description="从场景节点创建 prefab。底层 prefab_create_prefab。",
            inputSchema={
                "type": "object",
                "properties": {
                    "nodeUuid": {"type": "string", "description": "源节点 UUID"},
                    "savePath": {"type": "string", "description": "保存路径，如 db://assets/prefabs/MyPrefab.prefab"},
                    "prefabName": {"type": "string", "description": "prefab 名称"},
                },
                "required": ["nodeUuid", "savePath", "prefabName"],
            },
        ),
        Tool(
            name="cocos_prefab_duplicate",
            description="复制 prefab。底层 prefab_duplicate_prefab。",
            inputSchema={
                "type": "object",
                "properties": {
                    "sourcePrefabPath": {"type": "string", "description": "源 prefab 路径"},
                    "targetPrefabPath": {"type": "string", "description": "目标 prefab 路径"},
                    "newPrefabName": {"type": "string", "description": "新 prefab 名称（可选）"},
                },
                "required": ["sourcePrefabPath", "targetPrefabPath"],
            },
        ),
        Tool(
            name="cocos_prefab_revert",
            description="把 prefab 实例还原为原始。底层 prefab_revert_prefab。",
            inputSchema={
                "type": "object",
                "properties": {
                    "nodeUuid": {"type": "string", "description": "prefab 实例节点 UUID"},
                },
                "required": ["nodeUuid"],
            },
        ),
        Tool(
            name="cocos_attach_script",
            description="给节点挂脚本组件。底层 component_attach_script。挂自定义 TS 脚本到节点（含 prefab 根节点）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "nodeUuid": {"type": "string", "description": "节点 UUID"},
                    "scriptPath": {"type": "string", "description": "脚本资源路径，如 db://assets/plugins/debug/scripts/DebugView.ts"},
                },
                "required": ["nodeUuid", "scriptPath"],
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
        elif name == "cocos_attach_script":
            result = await _cocos_attach_script(
                nodeUuid=args["nodeUuid"],
                scriptPath=args["scriptPath"],
            )
        # ── Prefab 操作 ──
        elif name == "cocos_prefab_list":
            result = await _cocos_prefab_list(folder=args.get("folder", "db://assets"))
        elif name == "cocos_prefab_load":
            result = await _cocos_prefab_load(prefabPath=args["prefabPath"])
        elif name == "cocos_prefab_info":
            result = await _cocos_prefab_info(prefabPath=args["prefabPath"])
        elif name == "cocos_prefab_validate":
            result = await _cocos_prefab_validate(prefabPath=args["prefabPath"])
        elif name == "cocos_prefab_save":
            result = await _cocos_prefab_save(prefabPath=args["prefabPath"], nodeUuid=args["nodeUuid"])
        elif name == "cocos_prefab_instantiate":
            result = await _cocos_prefab_instantiate(
                prefabPath=args["prefabPath"],
                parentUuid=args.get("parentUuid", ""),
                position=args.get("position"),
            )
        elif name == "cocos_prefab_create":
            result = await _cocos_prefab_create(
                nodeUuid=args["nodeUuid"],
                savePath=args["savePath"],
                prefabName=args["prefabName"],
            )
        elif name == "cocos_prefab_duplicate":
            result = await _cocos_prefab_duplicate(
                sourcePrefabPath=args["sourcePrefabPath"],
                targetPrefabPath=args["targetPrefabPath"],
                newPrefabName=args.get("newPrefabName", ""),
            )
        elif name == "cocos_prefab_revert":
            result = await _cocos_prefab_revert(nodeUuid=args["nodeUuid"])
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
