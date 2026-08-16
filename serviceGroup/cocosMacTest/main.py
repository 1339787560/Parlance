#!/usr/bin/env python3
"""cocos-mac test — cocos 项目资源树陈列 + 编辑态查询测试子服务。

功能:
- 陈列指定目录(win/mac 分开)下 cocos 项目的资源管理器内容(assets 树, 可折叠)
- 编辑态查询操作(走 cocos_fs 纯函数, 零 MCP/编辑器):
    tree(节点树, 深度限制) / node(节点查询, 同名全返+组件属性)
    uuid(uuid 信息) / refs(uuid 引用) / find-file(按名称/类型查找文件)

用法:
    python main.py --port 5010 [--host 127.0.0.1]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# cocos_fs 纯函数库(同目录, 与 skillrepo tools/cocos_fs.py 同步)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cocos_fs

# ── 配置 ────────────────────────────────────────────────────────────────────

# 项目根目录(win/mac 分开)。当前机器只可达本平台路径, 另一平台段显示不可达。
PROJECT_ROOTS: Dict[str, str] = {
    "mac": "/Users/liz/codlib/cocos",
    "win": r"D:\Codlib\douque\xzmx\ClientEngineGame\3DDemo",
}

# 查询结果 JSON 截断上限(前端内联展示, 防超大响应)
MAX_RESPONSE = 200 * 1024

app = FastAPI(title="cocos-mac test", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 工具函数 ────────────────────────────────────────────────────────────────

def _is_cocos_project(d: Path) -> bool:
    """cocos 项目判定: 含 assets/ 子目录 + package.json。"""
    return (d / "assets").is_dir() and (d / "package.json").is_file()


def _check_project(project: str) -> Path:
    """信任边界: 项目必须位于某平台根目录内。"""
    p = Path(project).resolve()
    for root in PROJECT_ROOTS.values():
        rp = Path(root).resolve()
        if rp.is_dir():
            try:
                p.relative_to(rp)
                return p
            except ValueError:
                continue
    raise HTTPException(status_code=403, detail=f"项目不在允许范围内: {project}")


def _uuid_from_asset(project: str, asset: str) -> str:
    """读资产 .meta 取 uuid。"""
    abs_path = cocos_fs.resolve_asset_path(asset, project)
    meta_path = abs_path + ".meta"
    if not os.path.isfile(meta_path):
        raise HTTPException(status_code=400, detail=f"无 .meta 文件: {abs_path}")
    try:
        meta = json.loads(Path(meta_path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail=f".meta 解析失败: {meta_path}")
    uuid = meta.get("uuid", "")
    if not uuid:
        raise HTTPException(status_code=400, detail=f".meta 无 uuid: {meta_path}")
    return uuid


def _est_tokens(text: str) -> int:
    """粗略 token 估算: CJK 每字 ~1 token, ASCII ~4 字符/token。"""
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return cjk + (len(text) - cjk) // 4


def _respond(op: str, res: Dict[str, Any]) -> Dict[str, Any]:
    """统一响应: 结果 JSON 序列化 + 超限截断。"""
    s = json.dumps(res, ensure_ascii=False, indent=2)
    truncated = len(s) > MAX_RESPONSE
    if truncated:
        s = s[:MAX_RESPONSE] + "\n… [结果超限已截断]"
    return {"ok": not res.get("error"), "op": op, "truncated": truncated, "text": s,
            "chars": len(s), "tokens": _est_tokens(s)}


def _text_response(op: str, text: str) -> Dict[str, Any]:
    """紧凑文本响应(已序列化, 直接展示)。"""
    truncated = len(text) > MAX_RESPONSE
    if truncated:
        text = text[:MAX_RESPONSE] + "\n… [结果超限已截断]"
    return {"ok": True, "op": op, "truncated": truncated, "text": text,
            "chars": len(text), "tokens": _est_tokens(text)}


# ── API ─────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def api_config() -> Dict[str, Any]:
    """前端引导配置: 平台根目录可达性。"""
    roots = {}
    for plat, root in PROJECT_ROOTS.items():
        rp = Path(root)
        roots[plat] = {"root": root, "accessible": rp.is_dir()}
    return {"platforms": ["win", "mac"], "roots": roots}


@app.get("/api/projects")
def api_projects() -> Dict[str, Any]:
    """扫描各平台项目根, 列出 cocos 项目。"""
    out: Dict[str, Any] = {}
    for plat, root in PROJECT_ROOTS.items():
        rp = Path(root)
        if not rp.is_dir():
            out[plat] = {"root": root, "accessible": False, "projects": []}
            continue
        projects = []
        for child in sorted(rp.iterdir()):
            if child.is_dir() and _is_cocos_project(child):
                projects.append({"name": child.name, "path": str(child)})
        out[plat] = {"root": root, "accessible": True, "projects": projects}
    return out


@app.get("/api/tree")
def api_tree(
    project: str = Query(..., description="项目绝对路径"),
    dir: str = Query("", description="目录绝对路径, 空=项目 assets 根"),
) -> Dict[str, Any]:
    """懒加载资源树: 返回指定目录一层条目。dir 空时返回 <project>/assets 根层。"""
    proj = _check_project(project)
    if not _is_cocos_project(proj):
        raise HTTPException(status_code=400, detail=f"非 cocos 项目: {project}")
    base = proj / "assets"
    if not base.is_dir():
        raise HTTPException(status_code=400, detail=f"项目无 assets/ 目录: {project}")
    target = Path(dir).resolve() if dir else base
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="目录超出项目 assets 范围")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在: {dir}")

    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.endswith(".meta"):
            continue  # 资源管理器不显示 .meta
        if child.is_dir():
            entries.append({"name": child.name, "path": str(child), "type": "dir"})
        else:
            entries.append({
                "name": child.name, "path": str(child), "type": "file",
                "ext": child.suffix.lstrip(".").lower(),
                "size": child.stat().st_size if child.is_file() else 0,
            })
    return {"project": str(proj), "dir": str(target), "entries": entries}


def _type_matches(t: str, query: str) -> bool:
    """组件类型匹配: 精确 / 去 cc. 前缀 / 子串。"""
    if not query:
        return True
    if t == query:
        return True
    stripped = t[3:] if t.startswith("cc.") else t
    return stripped == query or query in t or query in stripped


def _node_summary(nodes: list, matches: dict, component: str = "") -> str:
    """节点查询结果 → 紧凑文本摘要(节点属性 + 组件 + 绑定概览)。"""
    lines = []
    for i, n in enumerate(nodes):
        np = n.get("nodeProps", {})
        lines.append(f"  [{i+1}] {n['path']}  {'inactive!' if not n['active'] else ''}")
        if np:
            pos = np.get("position") or ["-", "-", "-"]
            rot = np.get("rotation") or ["-", "-", "-"]
            scale = np.get("scale") or ["-", "-", "-"]
            lines.append(f"      pos[{pos[0]},{pos[1]},{pos[2]}] rot[{rot[0]},{rot[1]},{rot[2]}] "
                         f"scale[{scale[0]},{scale[1]},{scale[2]}] layer[{np.get('layer')}] 子节点[{np.get('childCount')}]")
        for c in n.get("components", []):
            lines.append(f"      {c.get('type', '?')}: {len(c.get('properties', {}))} 属性, {len(c.get('refs', []))} 绑定")
            for r in c.get("refs", [])[:6]:
                lines.append(f"        · {r.get('prop')} → {r.get('asset') or r.get('uuid')}")
    head = (f"node: {len(nodes)} 个节点 ({matches.get('nodeName')}"
            + (", fuzzy 匹配" if matches.get("fuzzy") else "")
            + (f", 组件过滤 {component}" if component else "") + ")")
    return head + "\n" + "\n".join(lines)


@app.post("/api/query")
def api_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    """编辑态查询: {op, project, asset?, node?, depth?, uuid?, pattern?, type?}。

    op:
      tree      节点树(asset + depth, 深度限制)
      node      节点查询(asset + node, 同名全返 + 组件属性)
      uuid      uuid 信息(asset, 从 .meta 取 uuid)
      refs      uuid 引用(asset, 从 .meta 取 uuid)
      find-file 查找文件(project + pattern + type)
    """
    op = payload.get("op", "")
    project = payload.get("project", "")
    proj = _check_project(project)

    if op == "tree":
        asset = payload.get("asset", "")
        depth = int(payload.get("depth", 2))
        res = cocos_fs.build_scene_tree(asset, max_depth=depth, project_path=str(proj))
        if not res.get("error") and res.get("root"):
            depth_str = "∞" if depth <= 0 else str(depth)
            head = f"{res['resolvedPath']} (depth {depth_str}, {res['totalObjects']} 对象)"
            if payload.get("node"):
                head += f", 节点 {payload['node']}"
            return _text_response(op, head + "\n" + cocos_fs.tree_to_text(res["root"]))
    elif op == "node":
        asset = payload.get("asset", "")
        node = payload.get("node", "")
        fuzzy = bool(payload.get("fuzzy", False))
        component = payload.get("component", "")
        cross = bool(payload.get("all", False))
        if cross:
            matches = cocos_fs.find_nodes_in_tree(asset, node, str(proj), fuzzy=fuzzy)
        else:
            matches = cocos_fs.find_nodes_by_name(asset, node, str(proj), fuzzy=fuzzy)
        if matches.get("error"):
            res = matches
        else:
            nodes = []
            for m in matches.get("nodes", []):
                file_ = m.get("file") or asset
                file_path = m.get("filePath") or m["path"]
                comps = cocos_fs.build_node_components(file_, file_path, str(proj))
                if comps.get("error"):
                    continue
                if component:
                    comps["components"] = [c for c in comps.get("components", [])
                                           if _type_matches(c.get("type", ""), component)]
                nodes.append({
                    "path": m["path"], "active": m["active"],
                    "file": file_, "filePath": file_path,
                    "nodeProps": comps.get("nodeProps", {}),
                    "components": comps.get("components", []),
                })
            return _text_response(op, _node_summary(nodes, matches, component))
    elif op == "uuid":
        asset = payload.get("asset", "")
        uuid = _uuid_from_asset(str(proj), asset)
        res = cocos_fs.lookup_uuid(str(proj), uuid)
    elif op == "refs":
        asset = payload.get("asset", "")
        uuid = _uuid_from_asset(str(proj), asset)
        res = cocos_fs.find_uuid_refs(str(proj), uuid)
    elif op == "find-file":
        pattern = payload.get("pattern", "")
        type_ = payload.get("type", "")
        res = cocos_fs.find_assets("db://assets", type_, pattern, str(proj), 50)
    else:
        raise HTTPException(status_code=400, detail=f"未知操作: {op}")

    return _respond(op, res)


# 静态前端
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="cocos-mac test 子服务")
    parser.add_argument("--port", type=int, default=5010)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")