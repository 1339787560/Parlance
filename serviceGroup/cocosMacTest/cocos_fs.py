#!/usr/bin/env python3
"""
Cocos fs layer — 纯 Python 文件系统 + JSON 解析逻辑。

读 .scene/.prefab/.meta 直接拿节点树/组件/资产，零 Editor.Message 开销。
设计为可被 Rust exe 替换的纯函数集（无 MCP/网络依赖）。

Cocos 3.8 文件格式要点:
- .scene / .prefab: 顶层数组, 每元素带 __type__, __id__ 隐式 = 数组下标
- 引用靠 {"__id__": N} 指向数组元素
- cc.Prefab[0].data.__id__ → 根节点; cc.SceneAsset[0].scene.__id__ → cc.Scene
- 节点字段: _name / _children:[{__id__}] / _components:[{__id__}] / _active / _lpos / _lrot / _lscale / _layer / _prefab
- 组件字段: __type__ (类名或脚本 uuid) + 各 _prop 私有字段
- .meta: {ver, importer, uuid, subMetas, userData} — importer 标类型(texture/prefab/scene/...)
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── 路径解析 ────────────────────────────────────────────────────────────────

def resolve_asset_path(asset_path: str, project_path: str = "") -> str:
    """解析 db:// URL / 相对路径 / 绝对路径 → OS 绝对路径。

    - db://assets/foo/bar.prefab → <project_path>/assets/foo/bar.prefab
    - 相对路径 → 拼到 project_path 下
    - 绝对路径 → 直接返
    """
    if asset_path.startswith("db://"):
        if not project_path:
            raise ValueError("db:// URL 需 projectPath, 传 projectPath 参数或先调 cocos_set_project")
        rel = asset_path[len("db://"):]
        return os.path.join(project_path, rel.replace("/", os.sep))
    if os.path.isabs(asset_path):
        return asset_path
    if project_path:
        return os.path.join(project_path, asset_path.replace("/", os.sep))
    return asset_path


# ── 加载与根节点定位 ─────────────────────────────────────────────────────────

def load_cocos_asset(asset_path: str) -> List[Dict[str, Any]]:
    """加载 .scene/.prefab JSON 为数组。非合法格式抛 ValueError。"""
    with open(asset_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"非 Cocos scene/prefab 格式(顶层数组): {asset_path}")
    return data


def find_root_index(data: List[Dict[str, Any]]) -> Optional[int]:
    """定位根节点数组下标。

    优先级: cc.Prefab.data.__id__ > cc.SceneAsset.scene.__id__ > 首个 _parent=null 的 cc.Node
    """
    for obj in data:
        t = obj.get("__type__", "")
        if t == "cc.Prefab" and isinstance(obj.get("data"), dict):
            return obj["data"].get("__id__")
        if t == "cc.SceneAsset" and isinstance(obj.get("scene"), dict):
            scene_idx = obj["scene"].get("__id__")
            if scene_idx is not None:
                # cc.Scene 节点本身（其 _children 是场景根节点集合）
                return scene_idx
    # fallback: 首个无父的 cc.Node
    for i, obj in enumerate(data):
        if obj.get("__type__") == "cc.Node" and obj.get("_parent") is None:
            return i
    return None


# ── 节点树构建 ───────────────────────────────────────────────────────────────

# uuid → 资产文件绝对路径 的 lazy 缓存(按 project_path 分桶)
# 嵌套 prefab 解析时按 _prefab.asset.__uuid__ 反查外部 prefab 文件路径
# 2026-08-16: 缓存带 mtime 失效 — CocosCreator 重组/重导入资产时 .meta 变,
# 旧索引按旧路径找文件失败 → 嵌套 prefab 显示 "?"。查询时扫 .meta 最大 mtime,
# 若晚于索引构建时间则自动重建(stat 不读内容, 快)。
_UUID_INDEX_CACHE: Dict[str, Dict[str, Any]] = {}
_UUID_RE = None
try:
    import re as _re
    _UUID_RE = _re.compile(r'"uuid"\s*:\s*"([0-9a-fA-F-]+)"')
except ImportError:
    pass


def _build_uuid_index(assets_dir: str):
    """扫 assets_dir 下所有 .meta, 建 {asset_uuid: 主资产文件绝对路径}。

    性能: 只读前 2KB + regex 抽 uuid(避全 JSON parse)。实测万级 .meta ~1-2s。
    返回 (index, max_meta_mtime)。
    """
    import re as _re
    uuid_re = _re.compile(r'"uuid"\s*:\s*"([0-9a-fA-F-]+)"')
    index: Dict[str, str] = {}
    max_mtime = 0.0
    if not os.path.isdir(assets_dir):
        return index, max_mtime
    for root, dirs, files in os.walk(assets_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('Temp', 'library')]
        for fname in files:
            if not fname.endswith('.meta'):
                continue
            path = os.path.join(root, fname)
            try:
                st = os.stat(path)
                if st.st_mtime > max_mtime:
                    max_mtime = st.st_mtime
                # uuid 在 .meta 头部, 读前 2KB 足够 + regex 比 json.load 快 5-10×
                with open(path, 'rb') as f:
                    head = f.read(2048)
                m = uuid_re.search(head.decode('utf-8-sig', errors='ignore'))
                if m:
                    index[m.group(1)] = path[:-5]  # 去 .meta 后缀
            except Exception:
                continue
    return index, max_mtime


def _scan_meta_mtimes(assets_dir: str) -> float:
    """assets/ 下 .meta 文件的最大 mtime (仅 stat, 不读内容, ~100ms/万级)。"""
    latest = 0.0
    if not os.path.isdir(assets_dir):
        return latest
    for root, dirs, files in os.walk(assets_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('Temp', 'library')]
        for fname in files:
            if not fname.endswith('.meta'):
                continue
            try:
                st = os.stat(os.path.join(root, fname))
                if st.st_mtime > latest:
                    latest = st.st_mtime
            except OSError:
                continue
    return latest


def _get_uuid_index(project_path: str) -> Dict[str, str]:
    """取/建 project_path 的 uuid→路径索引。

    mtime 失效: 每次调用先扫 .meta 最大 mtime, 若晚于索引构建时间 → 重建。
    项目未被 CocosCreator 改动时命中缓存(扫描开销仅 ~100ms)。
    """
    if not project_path:
        return {}
    assets_dir = os.path.join(project_path, 'assets')
    latest = _scan_meta_mtimes(assets_dir)
    cached = _UUID_INDEX_CACHE.get(project_path)
    if cached and latest <= cached.get("max_mtime", 0):
        return cached["index"]
    index, max_mtime = _build_uuid_index(assets_dir)
    _UUID_INDEX_CACHE[project_path] = {"index": index, "max_mtime": max_mtime}
    return index


def _walk_tree(
    data: List[Dict[str, Any]],
    idx: int,
    depth: int,
    max_depth: int,
    parent_path: str,
    include_inactive: bool,
    ctx: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """递归构建紧凑节点字典。ctx 携带嵌套 prefab 解析上下文(可选)。"""
    if idx < 0 or idx >= len(data):
        return None
    node = data[idx]
    # cc.Scene 在文件里 __type__="cc.Scene" 非cc.Node, 但语义是节点容器(_children 可走)
    if node.get("__type__") not in ("cc.Node", "cc.Scene"):
        # 引用指向非节点(异常), 返占位
        return {"error": f"non-node at __id__ {idx}", "type": node.get("__type__")}

    name = node.get("_name") or "?"
    active = node.get("_active", True)
    if not active and not include_inactive:
        return None
    node_path = (parent_path + "/" + name) if parent_path else name

    # ── 嵌套 prefab 实例解析 ──
    # 节点 _prefab 指向 PrefabInfo, 若 PrefabInfo.root.__id__ == idx (本节点是实例根)
    # 且 asset.__uuid__ 存在 → 跨文件加载外部 prefab, 用其根替换本节点(继承 parent_path)
    # 循环检测: 用 resolution_chain(当前解析路径上的 uuid 栈), 非 global visited。
    # 同 uuid 在兄弟节点多次实例化(如 3 个 CardMJ)应各自解析, 不互相屏蔽。
    # 深度边界(depth == max_depth)也解析: 只取外部根节点名/组件, 不展开子节点,
    # 避免占位 "?" 出现在树边界(2026-08-16 修复)。
    if ctx is not None:
        prefab_ref = node.get("_prefab")
        if isinstance(prefab_ref, dict) and "__id__" in prefab_ref:
            pi_idx = prefab_ref["__id__"]
            if 0 <= pi_idx < len(data):
                pi = data[pi_idx]
                asset_uuid = ((pi.get("asset") or {}).get("__uuid__") or "").strip()
                root_id = (pi.get("root") or {}).get("__id__")
                is_instance_root = root_id == idx and bool(asset_uuid)
                nest_depth = ctx.get("nest_depth", 0)
                max_nest = ctx.get("max_nest", 3)
                chain = ctx.setdefault("resolution_chain", [])
                if (is_instance_root and asset_uuid not in chain
                        and nest_depth < max_nest):
                    ext_path = ctx.get("uuid_index", {}).get(asset_uuid)
                    if ext_path and os.path.isfile(ext_path):
                        try:
                            ext_data = load_cocos_asset(ext_path)
                            ext_root_idx = find_root_index(ext_data)
                            if ext_root_idx is not None:
                                chain.append(asset_uuid)
                                ctx["nest_depth"] = nest_depth + 1
                                ctx["resolved_count"] = ctx.get("resolved_count", 0) + 1
                                # 外部 prefab 用剩余深度预算 + 原 parent_path 继承
                                ext_tree = _walk_tree(
                                    ext_data, ext_root_idx, depth, max_depth,
                                    parent_path, include_inactive, ctx,
                                )
                                ctx["nest_depth"] = nest_depth
                                chain.pop()
                                if ext_tree and isinstance(ext_tree, dict):
                                    ext_tree["_nestedFromUuid"] = asset_uuid
                                    ext_tree["_nestedPath"] = os.path.relpath(ext_path, ctx.get("project_path", "")).replace(os.sep, "/") if ctx.get("project_path") else ext_path
                                    # 实例自身新增 children: prefab 内容在外部文件,
                                    # 宿主文件里实例根的 _children = 实例化后额外添加的节点
                                    extra_refs = node.get("_children", []) or []
                                    if extra_refs:
                                        extras = []
                                        base_path = ext_tree.get("path") or node_path
                                        for child_ref in extra_refs:
                                            cid = child_ref.get("__id__")
                                            if cid is None:
                                                continue
                                            child = _walk_tree(
                                                data, cid, depth + 1, max_depth,
                                                base_path, include_inactive, ctx,
                                            )
                                            if child is not None:
                                                extras.append(child)
                                        if extras:
                                            ext_tree["_nestedExtra"] = extras
                                    return ext_tree
                        except (json.JSONDecodeError, ValueError):
                            pass  # 解析失败降级走正常 walk

    # 组件: 仅取 __type__ + 脚本组件解析为脚本名, 不读属性(避重 dump)
    comps = []
    for comp_ref in node.get("_components", []) or []:
        cid = comp_ref.get("__id__")
        if cid is None or cid < 0 or cid >= len(data):
            continue
        cobj = data[cid]
        ctype = cobj.get("__type__", "?")
        comp = {"type": ctype, "index": cid}
        # 脚本组件(非 cc. 前缀 + 压缩 uuid 形态): 反查脚本资产名, 提升可读性
        if (ctx is not None and not ctype.startswith("cc.")
                and not ctype.startswith(("dragonBones", "sp.", "CC"))
                and len(ctype.split("@", 1)[0]) in (22, 23)):
            resolved = resolve_script_component(ctype, uuid_index=ctx.get("uuid_index"))
            if resolved.get("path"):
                comp["script"] = resolved["script"]
            elif resolved.get("missing"):
                comp["missing"] = True
        comps.append(comp)

    children = []
    # max_depth <= 0 = 不限深度(全量展开, 慎用防超大输出)
    if depth < max_depth or max_depth <= 0:
        for child_ref in node.get("_children", []) or []:
            cid = child_ref.get("__id__")
            if cid is None:
                continue
            child = _walk_tree(data, cid, depth + 1, max_depth, node_path, include_inactive, ctx)
            if child is not None:
                children.append(child)

    return {
        "name": name,
        "path": node_path,
        "active": active,
        "layer": node.get("_layer"),
        "components": comps,
        "childCount": len(node.get("_children", []) or []),
        "children": children,
    }


def build_scene_tree(
    asset_path: str,
    max_depth: int = 2,
    include_inactive: bool = True,
    project_path: str = "",
    path_filter: str = "",
    resolve_nested: bool = True,
    max_nest: int = 3,
) -> Dict[str, Any]:
    """读 .scene/.prefab 构建紧凑节点树。

    返 {assetPath, rootNode: {name, path, active, components:[{type,index}], children:[...]}}。
    组件只含 type+index(无属性值), 拿属性用 build_node_components。

    max_depth 默认 2(平衡 token: game.scene depth2=2.5K tok / depth3=8K tok / depth10=34K tok 爆)。
    max_depth <= 0 = 不限深度(全量展开; 嵌套 prefab 受 max_nest 限制)。
    path_filter 给定时只返该路径子树(如 'Node_GameDesk/Main Light'), 避免整场景 dump。
        - 精确匹配优先, 失败时末段模糊(多候选报错列出)。
    resolve_nested=true 时跨文件解析嵌套 prefab 实例(_prefab.asset.__uuid__ 反查外部 prefab
        文件, 用其根替换占位节点)。需 project_path。max_nest 限嵌套深度(默认 3)。
        外部 prefab 用剩余 depth 预算。注: 不应用 instance targetOverrides(实例覆盖), 显示默认值。
    """
    abs_path = resolve_asset_path(asset_path, project_path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {abs_path}"}
    try:
        data = load_cocos_asset(abs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"解析失败: {e}"}

    root_idx = find_root_index(data)
    if root_idx is None:
        return {"error": "未找到根节点(非 cc.Prefab/cc.SceneAsset/cc.Node 格式)"}

    start_idx = root_idx
    start_parent_path = ""
    if path_filter:
        path_index = _build_path_index(data, root_idx)
        target_idx = path_index.get(path_filter)
        if target_idx is None:
            suffix = path_filter.rsplit("/", 1)[-1]
            cands = [p for p in path_index if p.endswith("/" + suffix) or p == suffix]
            if len(cands) == 1:
                target_idx = path_index[cands[0]]
                path_filter = cands[0]
            elif cands:
                return {"error": f"path_filter 不唯一, 候选: {cands[:10]}", "pathFilter": path_filter}
            else:
                return {"error": f"path_filter 未找到: {path_filter}", "availablePathsSample": list(path_index.keys())[:30]}
        start_idx = target_idx
        # 让 walker 拼出绝对路径: parent_path + "/" + node_name = path_filter
        start_parent_path = path_filter.rsplit("/", 1)[0] if "/" in path_filter else ""

    ctx: Optional[Dict[str, Any]] = None
    if resolve_nested and project_path:
        ctx = {
            "uuid_index": _get_uuid_index(project_path),
            "project_path": project_path,
            "resolution_chain": [],  # 当前解析链(uuid 栈), 循环检测用
            "nest_depth": 0,
            "max_nest": max_nest,
            "resolved_count": 0,
        }

    tree = _walk_tree(data, start_idx, 0, max_depth, start_parent_path, include_inactive, ctx)
    return {
        "assetPath": asset_path,
        "resolvedPath": abs_path,
        "totalObjects": len(data),
        "pathFilter": path_filter or None,
        "nestedResolved": ctx.get("resolved_count", 0) if ctx else 0,
        "root": tree,
    }


# ── 节点定位与组件详情 ──────────────────────────────────────────────────────

def _build_path_index(data: List[Dict[str, Any]], root_idx: int) -> Dict[str, int]:
    """构建 path → 节点数组下标 的映射(全树扫一次)。

    与 _walk_tree 一致: 根可为 cc.Scene(场景容器)或 cc.Node。
    """
    index: Dict[str, int] = {}

    def walk(idx: int, parent_path: str):
        node = data[idx]
        if node.get("__type__") not in ("cc.Node", "cc.Scene"):
            return
        name = node.get("_name", "?")
        node_path = (parent_path + "/" + name) if parent_path else name
        index[node_path] = idx
        for child_ref in node.get("_children", []):
            cid = child_ref.get("__id__")
            if cid is not None:
                walk(cid, node_path)

    walk(root_idx, "")
    return index


def _filter_comp_fields(cobj: Dict[str, Any]) -> Dict[str, Any]:
    """过滤组件字段: 跳过内部下划线字段 + 元信息, 保留业务属性。

    Cocos 序列化字段多数以 _ 前缀存私有; 此处保留它们但去掉纯内部字段。
    返 {propName: value}, propName 去掉 _ 前缀(与 Editor 公开属性名对齐)。
    """
    skip = {"__type__", "__editorExtras__", "_objFlags", "_name", "node", "_id",
            "__prefab", "__scriptAsset"}
    out: Dict[str, Any] = {}
    for k, v in cobj.items():
        if k in skip:
            continue
        # 去掉私有下划线前缀, 与 Editor Inspector 公开名对齐
        pub = k[1:] if k.startswith("_") and not k.startswith("__") else k
        if pub in ("name", "enabled"):
            # enabled/name 是 cc.Component 基类公开字段, 保留原值
            out[pub] = v
        elif not pub.startswith("_"):
            out[pub] = v
    return out


def _vec3(v: Any) -> Optional[List[float]]:
    """cc.Vec3/cc.Vec2 字典 → [x, y, (z)]。"""
    if isinstance(v, dict):
        out = [v.get("x"), v.get("y")]
        if "z" in v:
            out.append(v.get("z"))
        return out
    return None


def _quat_to_euler(q: Any) -> Optional[List[float]]:
    """cc.Quat → 欧拉角(度)。"""
    if not isinstance(q, dict):
        return None
    x, y, z, w = q.get("x", 0), q.get("y", 0), q.get("z", 0), q.get("w", 1)
    import math
    # 归一化
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n == 0:
        return [0, 0, 0]
    x, y, z, w = x / n, y / n, z / n, w / n
    # ZYX 欧拉(与 Cocos 编辑器一致)
    sp = -2.0 * (y * z - w * x)
    if abs(sp) > 0.9999:
        # 万向锁
        pitch = math.copysign(math.pi / 2, sp)
        yaw = math.atan2(-x * z + w * y, 0.5 - y * y - z * z)
        roll = 0.0
    else:
        pitch = math.asin(sp)
        yaw = math.atan2(x * z + w * y, 0.5 - x * x - y * y)
        roll = math.atan2(x * y + w * z, 0.5 - x * x - z * z)
    deg = lambda r: round(math.degrees(r), 1)
    return [deg(roll), deg(pitch), deg(yaw)]


def _extract_refs(props: Dict[str, Any], uuid_index: Dict[str, str]) -> List[Dict[str, Any]]:
    """从组件属性中抽取资产绑定引用(__uuid__ 字段), 解析为资产路径。

    返 [{prop, uuid, type, asset}] — prop 为点路径(如 spriteFrame / material),
    type 为 __expectedType__ (如 cc.SpriteFrame), asset 为解析出的资产路径(空=未找到)。
    """
    refs: List[Dict[str, Any]] = []

    def walk(key: str, val: Any):
        if isinstance(val, dict):
            if "__uuid__" in val:
                u = val["__uuid__"]
                refs.append({
                    "prop": key,
                    "uuid": u,
                    "type": val.get("__expectedType__", ""),
                    "asset": uuid_index.get(u, ""),
                })
            else:
                for k, v in val.items():
                    walk(f"{key}.{k}", v)
        elif isinstance(val, list):
            for i, v in enumerate(val):
                walk(f"{key}[{i}]", v)

    for k, v in props.items():
        walk(k, v)
    return refs


def build_node_components(
    asset_path: str,
    node_path: str,
    project_path: str = "",
) -> Dict[str, Any]:
    """读文件定位节点, 返其全组件清单 + 各组件序列化属性值。

    node_path 是 build_scene_tree 返回的 path 字段(如 'Node_GameDesk/Main Light')。
    返 {assetPath, nodePath, components: [{type, index, enabled, properties:{prop:value}}]}。
    """
    abs_path = resolve_asset_path(asset_path, project_path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {abs_path}"}
    try:
        data = load_cocos_asset(abs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"解析失败: {e}"}

    root_idx = find_root_index(data)
    if root_idx is None:
        return {"error": "未找到根节点"}

    path_index = _build_path_index(data, root_idx)
    target_idx = path_index.get(node_path)
    if target_idx is None:
        # 模糊匹配: 末段名匹配
        suffix = node_path.rsplit("/", 1)[-1]
        candidates = [p for p in path_index if p.endswith("/" + suffix) or p == suffix]
        if len(candidates) == 1:
            target_idx = path_index[candidates[0]]
            node_path = candidates[0]
        elif candidates:
            return {"error": f"路径不唯一, 候选: {candidates}", "nodePath": node_path}
        else:
            return {"error": f"节点路径未找到: {node_path}", "availablePaths": list(path_index.keys())[:30]}

    node = data[target_idx]
    uuid_index = _get_uuid_index(project_path) if project_path else {}
    comps_out = []
    for comp_ref in node.get("_components", []):
        cid = comp_ref.get("__id__")
        if cid is None or cid < 0 or cid >= len(data):
            continue
        cobj = data[cid]
        props = _filter_comp_fields(cobj)
        comps_out.append({
            "type": cobj.get("__type__", "?"),
            "index": cid,
            "enabled": cobj.get("enabled", cobj.get("_enabled", True)),
            "properties": props,
            "refs": _extract_refs(props, uuid_index),
        })

    return {
        "assetPath": asset_path,
        "nodePath": node_path,
        "nodeName": node.get("_name"),
        "nodeProps": {
            "position": _vec3(node.get("_lpos")),
            "rotation": _quat_to_euler(node.get("_lrot")),
            "scale": _vec3(node.get("_lscale")),
            "active": node.get("_active", True),
            "layer": node.get("_layer"),
            "childCount": len(node.get("_children", []) or []),
        },
        "components": comps_out,
    }


# ── 组件属性写入(绑定/改值, 纯函数文件级) ────────────────────────────────────

def _locate_component_obj(
    data: List[Dict[str, Any]],
    node_path: str,
    comp_type: str = "",
    comp_index: int = -1,
) -> Dict[str, Any]:
    """定位组件对象(文件内数组下标)。comp_type 精确匹配优先, comp_index 兜底。

    返 {ok, cid, cobj, nodePath} 或 {error, ...}。
    """
    root_idx = find_root_index(data)
    if root_idx is None:
        return {"error": "未找到根节点(非 scene/prefab 格式)"}
    path_index = _build_path_index(data, root_idx)
    target_idx = path_index.get(node_path)
    if target_idx is None:
        suffix = node_path.rsplit("/", 1)[-1]
        cands = [p for p in path_index if p.endswith("/" + suffix) or p == suffix]
        if len(cands) == 1:
            target_idx = path_index[cands[0]]
            node_path = cands[0]
        elif cands:
            return {"error": f"路径不唯一, 候选: {cands}", "nodePath": node_path}
        else:
            return {"error": f"节点路径未找到: {node_path}", "nodePath": node_path}
    node = data[target_idx]
    comp_ids = [r.get("__id__") for r in (node.get("_components") or [])]
    # comp_index >= 0 且未给 type: 直接按下标
    if comp_index >= 0 and not comp_type:
        if comp_index >= len(comp_ids):
            return {"error": f"组件下标越界: {comp_index} >= {len(comp_ids)}", "nodePath": node_path}
        cid = comp_ids[comp_index]
        if cid is None or not (0 <= cid < len(data)):
            return {"error": f"组件 __id__ 无效: {cid}", "nodePath": node_path}
        return {"ok": True, "cid": cid, "cobj": data[cid], "nodePath": node_path}
    # 按类型匹配(可带 cc. 前缀或裸类名)
    for cid in comp_ids:
        if cid is None or not (0 <= cid < len(data)):
            continue
        t = data[cid].get("__type__", "")
        if t == comp_type or t[3:] == comp_type if t.startswith("cc.") else t == comp_type:
            return {"ok": True, "cid": cid, "cobj": data[cid], "nodePath": node_path}
    return {"error": f"组件未找到: {comp_type}", "nodePath": node_path}


def set_component_property(
    asset_path: str,
    node_path: str,
    comp_type: str = "",
    prop: str = "",
    value: Any = None,
    bind_uuid: str = "",
    bind_type: str = "",
    project_path: str = "",
    comp_index: int = -1,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """文件级组件属性写入(纯函数, 不改编辑器缓存)。

    - 普通值: set_component_property(asset, node, comp_type, prop, value)
    - 资产绑定: bind_uuid 给定时把 prop 写成 {"__uuid__": uuid, "__expectedType__": type}
      (跨文件资产引用, uuid 可传 db:// 路径或 36 位 uuid; 自动反查 uuid)
    - 文件内引用: value 传 {"__id__": N} 结构(指向文件数组下标, 如 node/子资产)

    返回 {ok, path, nodePath, compType, prop, before, after, data}。
    dry_run=True 只预览不落盘(无 .bak 无写文件)。
    写前自动备份 .bak, 不破坏原文件。**注意**: 直接改文件不改编辑器内缓存,
    需编辑器刷新(project_refresh_assets / 重开场景)才可见。
    """
    abs_path = resolve_asset_path(asset_path, project_path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {abs_path}"}
    if not prop:
        return {"error": "prop 必填(如 spriteFrame / _mjMesh / size)"}
    try:
        data = load_cocos_asset(abs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"解析失败: {e}"}

    loc = _locate_component_obj(data, node_path, comp_type, comp_index)
    if not loc.get("ok"):
        return loc
    cid, cobj, node_path = loc["cid"], loc["cobj"], loc["nodePath"]

    # 值解析: bind_uuid 优先(资产绑定), 否则原样 value
    if bind_uuid:
        target_uuid = bind_uuid
        if bind_uuid.startswith("db://"):
            # 路径 → uuid: 读 .meta
            abs_target = resolve_asset_path(bind_uuid, project_path)
            meta_path = abs_target + ".meta"
            if not os.path.isfile(meta_path):
                return {"error": f"绑定目标无 .meta: {bind_uuid}"}
            try:
                target_uuid = json.loads(Path(meta_path).read_text(encoding="utf-8-sig")).get("uuid", "")
            except json.JSONDecodeError:
                return {"error": f".meta 解析失败: {meta_path}"}
            if not target_uuid:
                return {"error": f".meta 无 uuid: {meta_path}"}
        bind_val = {"__uuid__": target_uuid}
        if bind_type:
            bind_val["__expectedType__"] = bind_type
        new_val = bind_val
    else:
        new_val = value

    # 找属性键: 先精确, 再 _ 前缀兼容
    keys = list(cobj.keys())
    if prop in cobj:
        old_val = cobj[prop]
    else:
        underscored = "_" + prop if not prop.startswith("_") else prop
        if underscored in cobj:
            prop_key = underscored
            old_val = cobj[prop_key]
        else:
            return {"error": f"属性不存在: {prop}", "availableProps": [k for k in keys if not k.startswith("__")][:30]}
        cobj[prop_key] = new_val
    if old_val == new_val:
        return {"ok": True, "path": abs_path, "nodePath": node_path, "compType": comp_type,
                "prop": prop, "changed": False, "before": old_val, "after": new_val,
                "dryRun": dry_run}
    if prop in cobj:
        cobj[prop] = new_val
    # dry-run: 只预览, 不写盘不备份
    if dry_run:
        return {"ok": True, "path": abs_path, "nodePath": node_path, "compType": comp_type,
                "prop": prop, "changed": True, "before": old_val, "after": new_val,
                "dryRun": True}
    # 写回(保留原文件 .bak)
    bak = abs_path + ".bak"
    if not os.path.exists(bak):
        try:
            os.replace(abs_path, bak)
        except OSError:
            pass
    Path(abs_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": abs_path, "nodePath": node_path, "compType": comp_type,
            "prop": prop, "changed": True, "before": old_val, "after": new_val,
            "dryRun": False}


# ── 全项目缺失扫描(missing script / missing node / missing asset) ───────────

def scan_missing(project_path: str, scan_type: str = "all") -> Dict[str, Any]:
    """扫描项目全部 .scene/.prefab, 收集三类缺失引用。

    scan_type: all / script / node / asset
    - script: 脚本组件 __type__(22/23 位压缩 uuid) 反查不到脚本资产 → missing script
    - node:   __id__ 引用越界 / 指向类型不符 → missing node(坏引用)
    - asset:  __uuid__ 资产引用在 uuid 索引中找不到 → missing asset

    返 {count, issues: [{kind, file, nodePath?, comp?, prop?, uuid?, detail}]}。
    全量扫 ~1-2s(复用 uuid 索引), 不写文件只读。
    """
    if not project_path or not os.path.isdir(os.path.join(project_path, "assets")):
        return {"error": f"无效项目根: {project_path}"}
    uuid_index = _get_uuid_index(project_path)
    # 引擎内置资源(编译进 Creator 二进制, 项目内无 .meta, 不算缺失)
    # 实测 3.8.1 常见: 默认白图/默认 spriteFrame/默认材质等
    _BUILTIN_UUIDS = {
        "20835ba4-6145-4fbc-a58a-051ce700aa3e",  # 默认贴图(白图)
        "544e49d6-3f05-4fa8-9a9e-091f98fc2ce8",  # 内置 spriteFrame
        "951249e0-9f16-456d-8b85-a6ca954da16b",  # 内置纹理
        "7d8f9b89-4fd1-4c9f-a3ab-38ec7cded7ca",  # 默认 spriteFrame
        "f12a23c4-b924-4322-a260-3d982428f1e8",  # 内置资源
        "45828f25-b50d-4c52-a591-e19491a62b8c",  # 默认材质
        "777f1101-6f5a-49e3-a232-9ef4bd598db1",  # 内置资源
        "57520716-48c8-4a19-8acf-41c9f8777fb0",  # 内置资源
        "28765e2f-040a-4c65-8e8c-f9d0bb79d863",  # 内置资源
        "6d93d377-a90b-4fcb-a0d1-69eb6537de04",  # 内置资源
        "a89c1129-6f18-4fc3-ad18-fa598c29db9c",  # 内置资源
    }
    issues = []

    def add(kind, f, node_path, comp, prop, uuid, detail):
        issues.append({"kind": kind, "file": f, "nodePath": node_path,
                       "comp": comp, "prop": prop, "uuid": uuid, "detail": detail})

    for root, dirs, files in os.walk(os.path.join(project_path, "assets")):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("Temp", "library")]
        for fname in files:
            if not fname.endswith((".scene", ".prefab")):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, project_path).replace(os.sep, "/")
            try:
                data = load_cocos_asset(fpath)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, list):
                continue
            # 节点名索引(报告用)
            name_of = {}
            for i, o in enumerate(data):
                if isinstance(o, dict):
                    name_of[i] = o.get("_name") or o.get("__type__") or "?"
            # ── 遍历所有对象, 收集 __id__ / __uuid__ / 脚本组件引用 ──
            for i, o in enumerate(data):
                if not isinstance(o, dict):
                    continue
                otype = o.get("__type__", "")
                # 脚本组件(非引擎类型): __type__ 是压缩 uuid
                base_type = otype.split("@", 1)[0]
                if (otype and not otype.startswith("cc.")
                        and not otype.startswith(("dragonBones", "sp.", "CC", "cc"))
                        and len(base_type) in (22, 23)
                        and otype != "CCPropertyOverrideInfo"):
                    if scan_type in ("all", "script"):
                        full = decode_uuid(otype)
                        if full and "-" in full and full not in uuid_index:
                            add("script", rel, name_of.get(i), otype, None, full,
                                "脚本组件引用项目内不存在的脚本资产")
                # __id__ 引用检查(节点/资产文件内引用)
                if scan_type in ("all", "node"):
                    for k, v in o.items():
                        if k.startswith("__"):
                            continue
                        if isinstance(v, dict) and "__id__" in v:
                            rid = v["__id__"]
                            if not isinstance(rid, int) or not (0 <= rid < len(data)):
                                add("node", rel, name_of.get(i), otype, k, None,
                                    f"__id__ 越界: {rid} (数组长 {len(data)})")
                # __uuid__ 资产引用
                if scan_type in ("all", "asset"):
                    for k, v in o.items():
                        if isinstance(v, dict) and "__uuid__" in v:
                            u = v["__uuid__"]
                            base_u = u.split("@", 1)[0]
                            if (base_u and base_u not in uuid_index
                                    and base_u not in _BUILTIN_UUIDS):
                                add("asset", rel, name_of.get(i), otype, k, u,
                                    "资产引用在项目 .meta 中未找到")

    return {"count": len(issues), "issues": issues,
            "summary": {"script": sum(1 for x in issues if x["kind"] == "script"),
                        "node": sum(1 for x in issues if x["kind"] == "node"),
                        "asset": sum(1 for x in issues if x["kind"] == "asset")}}


# ── 节点/组件 新增与删除(文件级写, 纯函数, .bak 备份) ────────────────────────
#
# Cocos 3.8 序列化: 顶层数组, __id__ 隐式 = 数组下标, 引用靠 {"__id__": N}。
# 新增节点/组件 = append 新对象到数组尾 + 更新父节点 _children / 节点 _components 引用。
# 删除节点/组件 = 从引用数组摘除 + 从扁平数组移除(重建 __id__ 映射, 防下标漂移)。

def _write_back(abs_path: str, data: List[Dict[str, Any]], dry_run: bool) -> Dict[str, Any]:
    """统一写回: dry_run 只预览; 否则 .bak 备份 + 落盘。返 (ok, msg)。"""
    if dry_run:
        return {"ok": True, "dryRun": True, "message": "dry-run 预览, 未写盘"}
    bak = abs_path + ".bak"
    if not os.path.exists(bak):
        try:
            os.replace(abs_path, bak)
        except OSError:
            pass
    Path(abs_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "dryRun": False, "message": "已写盘(.bak 已备份)"}


# 常用组件最小序列化模板(字段与编辑器序列化一致, 缺省可被编辑器补默认值)
_COMP_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "cc.UITransform": {
        "__type__": "cc.UITransform", "_name": "", "_objFlags": 0, "_enabled": True,
        "_contentSize": {"__type__": "cc.Size", "width": 100, "height": 100},
        "_anchorPoint": {"__type__": "cc.Vec2", "x": 0.5, "y": 0.5},
    },
    "cc.Sprite": {
        "__type__": "cc.Sprite", "_name": "", "_objFlags": 0, "_enabled": True,
        "_spriteFrame": None, "_type": 0, "_fillType": 0, "_sizeMode": 0,
        "_trim": True, "_srcBlendFactor": 2, "_dstBlendFactor": 4,
        "_color": {"__type__": "cc.Color", "r": 255, "g": 255, "b": 255, "a": 255},
    },
    "cc.Label": {
        "__type__": "cc.Label", "_name": "", "_objFlags": 0, "_enabled": True,
        "_string": "Label", "_fontSize": 40, "_lineHeight": 40,
        "_useSystemFont": True, "_horizontalAlign": 1, "_verticalAlign": 1,
        "_color": {"__type__": "cc.Color", "r": 255, "g": 255, "b": 255, "a": 255},
    },
    "cc.Button": {
        "__type__": "cc.Button", "_name": "", "_objFlags": 0, "_enabled": True,
        "_transition": 1, "_normalColor": {"__type__": "cc.Color", "r": 255, "g": 255, "b": 255, "a": 255},
        "_pressedColor": {"__type__": "cc.Color", "r": 200, "g": 200, "b": 200, "a": 255},
        "_hoverColor": {"__type__": "cc.Color", "r": 235, "g": 235, "b": 235, "a": 255},
        "_disabledColor": {"__type__": "cc.Color", "r": 120, "g": 120, "b": 120, "a": 255},
    },
}


def _new_node_obj(name: str, parent_id: Optional[int], layer: int = 33554432) -> Dict[str, Any]:
    """构造新 cc.Node 序列化对象(挂入数组尾部, __id__ = len(data))。"""
    return {
        "__type__": "cc.Node", "_name": name, "_objFlags": 0,
        "_parent": ({"__id__": parent_id} if parent_id is not None else None),
        "_children": [], "_active": True, "_components": [],
        "_prefab": None,
        "_lpos": {"__type__": "cc.Vec3", "x": 0, "y": 0, "z": 0},
        "_lrot": {"__type__": "cc.Quat", "x": 0, "y": 0, "z": 0, "w": 1},
        "_lscale": {"__type__": "cc.Vec3", "x": 1, "y": 1, "z": 1},
        "_mobility": 0, "_layer": layer,
        "_euler": {"__type__": "cc.Vec3", "x": 0, "y": 0, "z": 0},
        "_id": "",
    }


def add_node(
    asset_path: str,
    parent_path: str,
    name: str,
    project_path: str = "",
    comp_types: Optional[List[str]] = None,
    layer: int = 33554432,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """文件级新增子节点(可选挂组件)。

    - parent_path: 父节点路径(场景/prefab 内, 如 'Canvas/Panel'); 空 = 挂根
    - comp_types: 组件类型列表, 如 ["cc.UITransform", "cc.Sprite"]
    - 返回 {ok, path, parentPath, node, nodeId, components, dryRun}
    """
    abs_path = resolve_asset_path(asset_path, project_path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {abs_path}"}
    if not name:
        return {"error": "name 必填"}
    try:
        data = load_cocos_asset(abs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"解析失败: {e}"}

    root_idx = find_root_index(data)
    if root_idx is None:
        return {"error": "未找到根节点(非 scene/prefab 格式)"}

    parent_id: Optional[int] = None
    if parent_path:
        idx = _build_path_index(data, root_idx)
        parent_id = idx.get(parent_path)
        if parent_id is None:
            return {"error": f"父节点路径未找到: {parent_path}",
                    "availableRoots": list(idx.keys())[:20]}
    else:
        parent_id = root_idx

    node_id = len(data)
    node_obj = _new_node_obj(name, parent_id, layer)
    comp_ids = []
    # 先 append 组件(占位 node 引用), 再 append 节点, 最后回填组件 node 反向引用
    for ct in comp_types or []:
        comp_obj = dict(_COMP_TEMPLATES.get(ct, {"__type__": ct, "_name": "", "_objFlags": 0,
                                                 "_enabled": True}))
        comp_id = len(data)
        comp_ids.append(comp_id)
        comp_obj["node"] = {"__id__": node_id}
        node_obj["_components"].append({"__id__": comp_id})
        data.append(comp_obj)
    node_id = len(data)
    node_obj = _new_node_obj(name, parent_id, layer)
    node_obj["_components"] = [{"__id__": c} for c in comp_ids]
    for cid in comp_ids:
        data[cid]["node"] = {"__id__": node_id}
    data.append(node_obj)
    # 父节点 _children 引用新节点
    data[parent_id].setdefault("_children", []).append({"__id__": node_id})

    wr = _write_back(abs_path, data, dry_run)
    return {"ok": True, "path": abs_path, "parentPath": parent_path or "(根)",
            "node": name, "nodeId": node_id, "components": comp_ids,
            "dryRun": dry_run, "write": wr["message"]}


def add_component(
    asset_path: str,
    node_path: str,
    comp_type: str,
    project_path: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """文件级给节点新增组件(挂到 _components + append 数组尾)。

    支持内置模板(cc.UITransform/Sprite/Label/Button), 其他类型生成最小骨架。
    """
    abs_path = resolve_asset_path(asset_path, project_path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {abs_path}"}
    if not comp_type:
        return {"error": "comp_type 必填(如 cc.UITransform)"}
    try:
        data = load_cocos_asset(abs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"解析失败: {e}"}

    root_idx = find_root_index(data)
    if root_idx is None:
        return {"error": "未找到根节点(非 scene/prefab 格式)"}
    idx = _build_path_index(data, root_idx)
    node_id = idx.get(node_path)
    if node_id is None:
        suffix = node_path.rsplit("/", 1)[-1]
        cands = [p for p in idx if p.endswith("/" + suffix) or p == suffix]
        if len(cands) == 1:
            node_id = idx[cands[0]]
            node_path = cands[0]
        elif cands:
            return {"error": f"节点路径不唯一, 候选: {cands}", "nodePath": node_path}
        else:
            return {"error": f"节点路径未找到: {node_path}",
                    "availableRoots": list(idx.keys())[:20]}

    comp_obj = dict(_COMP_TEMPLATES.get(comp_type, {"__type__": comp_type, "_name": "",
                                                    "_objFlags": 0, "_enabled": True}))
    comp_obj["node"] = {"__id__": node_id}
    comp_id = len(data)
    data.append(comp_obj)
    data[node_id].setdefault("_components", []).append({"__id__": comp_id})

    wr = _write_back(abs_path, data, dry_run)
    return {"ok": True, "path": abs_path, "nodePath": node_path,
            "compType": comp_type, "compId": comp_id,
            "dryRun": dry_run, "write": wr["message"]}


def _collect_subtree_ids(data: List[Dict[str, Any]], node_id: int) -> set:
    """收集节点及其子树(所有后代节点 + 其组件)的数组下标集合。"""
    ids: set = set()

    def walk(nid: int):
        if nid in ids:
            return
        ids.add(nid)
        node = data[nid]
        for comp_ref in node.get("_components", []) or []:
            cid = comp_ref.get("__id__")
            if cid is not None and 0 <= cid < len(data):
                ids.add(cid)
        for child_ref in node.get("_children", []) or []:
            cid = child_ref.get("__id__")
            if cid is not None and 0 <= cid < len(data):
                walk(cid)

    walk(node_id)
    return ids


def remove_node(
    asset_path: str,
    node_path: str,
    project_path: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """文件级删除节点(含子树 + 组件), 重建 __id__ 映射防下标漂移。

    - 从父节点 _children 摘除引用
    - 删除节点 + 全部后代节点 + 它们的组件
    - 删除后数组剩余对象按原序重排, 所有 __id__ 引用重建映射
    """
    abs_path = resolve_asset_path(asset_path, project_path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {abs_path}"}
    try:
        data = load_cocos_asset(abs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"解析失败: {e}"}

    root_idx = find_root_index(data)
    if root_idx is None:
        return {"error": "未找到根节点(非 scene/prefab 格式)"}
    idx = _build_path_index(data, root_idx)
    node_id = idx.get(node_path)
    if node_id is None:
        suffix = node_path.rsplit("/", 1)[-1]
        cands = [p for p in idx if p.endswith("/" + suffix) or p == suffix]
        if len(cands) == 1:
            node_id = idx[cands[0]]
            node_path = cands[0]
        elif cands:
            return {"error": f"节点路径不唯一, 候选: {cands}", "nodePath": node_path}
        else:
            return {"error": f"节点路径未找到: {node_path}",
                    "availableRoots": list(idx.keys())[:20]}

    if node_id == root_idx:
        return {"error": "不能删除根节点"}

    # 收集删除集(子树节点 + 组件), 并摘除父引用
    removed = _collect_subtree_ids(data, node_id)
    parent_ref = data[node_id].get("_parent")
    if isinstance(parent_ref, dict) and "__id__" in parent_ref:
        pid = parent_ref["__id__"]
        if 0 <= pid < len(data):
            children = data[pid].get("_children") or []
            data[pid]["_children"] = [r for r in children if r.get("__id__") != node_id]

    # 重建 __id__ 映射(剩余对象保序, 引用指向新下标)
    old2new: Dict[int, int] = {}
    new_data: List[Dict[str, Any]] = []
    for i, o in enumerate(data):
        if i in removed:
            continue
        old2new[i] = len(new_data)
        new_data.append(o)
    for o in new_data:
        _remap_ids(o, old2new)

    wr = _write_back(abs_path, new_data, dry_run)
    return {"ok": True, "path": abs_path, "nodePath": node_path,
            "removedCount": len(removed), "removedIds": sorted(removed),
            "dryRun": dry_run, "write": wr["message"]}


def _remap_ids(obj: Any, old2new: Dict[int, int]) -> None:
    """递归把对象内所有 {"__id__": old} 引用重映射到新下标。"""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "__id__" and isinstance(v, int):
                if v in old2new:
                    obj[k] = old2new[v]
            elif isinstance(v, (dict, list)):
                _remap_ids(v, old2new)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _remap_ids(item, old2new)


def remove_component(
    asset_path: str,
    node_path: str,
    comp_type: str = "",
    comp_index: int = -1,
    project_path: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """文件级移除节点组件: 从 _components 摘引用 + 数组删除 + __id__ 重映射。"""
    abs_path = resolve_asset_path(asset_path, project_path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {abs_path}"}
    try:
        data = load_cocos_asset(abs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"解析失败: {e}"}

    root_idx = find_root_index(data)
    if root_idx is None:
        return {"error": "未找到根节点(非 scene/prefab 格式)"}
    idx = _build_path_index(data, root_idx)
    node_id = idx.get(node_path)
    if node_id is None:
        suffix = node_path.rsplit("/", 1)[-1]
        cands = [p for p in idx if p.endswith("/" + suffix) or p == suffix]
        if len(cands) == 1:
            node_id = idx[cands[0]]
            node_path = cands[0]
        elif cands:
            return {"error": f"节点路径不唯一, 候选: {cands}", "nodePath": node_path}
        else:
            return {"error": f"节点路径未找到: {node_path}",
                    "availableRoots": list(idx.keys())[:20]}

    node = data[node_id]
    comp_ids = [r.get("__id__") for r in (node.get("_components") or [])]
    target: Optional[int] = None
    if comp_index >= 0 and not comp_type:
        if comp_index >= len(comp_ids):
            return {"error": f"组件下标越界: {comp_index} >= {len(comp_ids)}"}
        target = comp_ids[comp_index]
    else:
        for cid in comp_ids:
            if cid is None:
                continue
            t = data[cid].get("__type__", "")
            if t == comp_type or (t.startswith("cc.") and t[3:] == comp_type):
                target = cid
                break
    if target is None:
        avail = [data[cid].get("__type__", "?") if cid is not None else "?" for cid in comp_ids]
        return {"error": f"组件未找到: {comp_type}", "availableComps": avail}

    # 摘引用 + 删除数组元素 + 重映射
    node["_components"] = [r for r in (node.get("_components") or []) if r.get("__id__") != target]
    removed = {target}
    old2new: Dict[int, int] = {}
    new_data: List[Dict[str, Any]] = []
    for i, o in enumerate(data):
        if i in removed:
            continue
        old2new[i] = len(new_data)
        new_data.append(o)
    for o in new_data:
        _remap_ids(o, old2new)

    wr = _write_back(abs_path, new_data, dry_run)
    return {"ok": True, "path": abs_path, "nodePath": node_path,
            "compType": comp_type or f"index{comp_index}", "compId": target,
            "dryRun": dry_run, "write": wr["message"]}


# ── 资产搜索 ────────────────────────────────────────────────────────────────

# importer → 友好类型名映射
_IMPORTER_TYPE_MAP = {
    "scene": "cc.SceneAsset",
    "prefab": "cc.Prefab",
    "texture": "cc.Texture2D",
    "image": "cc.ImageAsset",
    "audio-clip": "cc.AudioClip",
    "animation-clip": "cc.AnimationClip",
    "material": "cc.Material",
    "effect": "cc.EffectAsset",
    "mesh": "cc.Mesh",
    "font": "cc.TTFFont",
    "bitmap-font": "cc.BitmapFont",
    "json": "cc.JsonAsset",
    "text": "cc.TextAsset",
    "typescript": "cc.ScriptAsset",
}


def find_assets(
    folder: str,
    asset_type: str = "",
    name_pattern: str = "",
    project_path: str = "",
    max_results: int = 200,
) -> Dict[str, Any]:
    """递归扫 assets folder, 读 .meta 拿 uuid + 类型, 按条件过滤。

    folder: 起始目录(db:// 或绝对路径或相对 project_path)
    asset_type: 资产类型, 多种形式兼容:
        - importer 名(scene/prefab/texture/material/effect/...)
        - 类名(cc.Prefab/cc.DirectionalLight/...)
    name_pattern: 名称子串(大小写不敏感)
    返 {folder, count, assets: [{uuid, path(db://), name, type, importer}]}。
    """
    abs_folder = resolve_asset_path(folder, project_path) if folder else (
        os.path.join(project_path, "assets") if project_path else folder
    )
    if not abs_folder or not os.path.isdir(abs_folder):
        return {"error": f"目录不存在: {abs_folder}", "folder": folder}

    # 归一化 asset_type 为 importer 名
    wanted_importer = ""
    wanted_class = ""
    if asset_type:
        if asset_type.startswith("cc."):
            wanted_class = asset_type
            # 反查 importer
            for imp, cls in _IMPORTER_TYPE_MAP.items():
                if cls == asset_type:
                    wanted_importer = imp
                    break
        else:
            wanted_importer = asset_type.lower()

    results = []
    name_lower = name_pattern.lower() if name_pattern else ""

    for root, dirs, files in os.walk(abs_folder):
        # 跳过 .creator/Temp/library 等内部目录
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("Temp", "library")]
        for fname in files:
            if not fname.endswith(".meta"):
                continue
            # 主资源文件 = 去 .meta 后缀
            asset_fname = fname[:-5]
            if asset_fname.endswith(".meta"):  # defensive
                continue
            stem, _ = os.path.splitext(asset_fname)
            if name_lower and name_lower not in stem.lower():
                continue

            meta_path = os.path.join(root, fname)
            try:
                with open(meta_path, "r", encoding="utf-8-sig") as f:
                    meta = json.load(f)
            except Exception:
                continue

            importer = meta.get("importer", "")
            uuid = meta.get("uuid", "")
            if not uuid:
                continue

            # 类型过滤
            if wanted_importer and importer != wanted_importer:
                continue
            # 类名过滤(importer 不可逆时读 userData)
            if wanted_class and not wanted_importer:
                ud = meta.get("userData", {})
                if ud.get("type") != wanted_class:
                    continue

            # 算 db:// path
            asset_abs = os.path.join(root, asset_fname)
            if project_path:
                rel_to_proj = os.path.relpath(asset_abs, project_path).replace(os.sep, "/")
                db_path = f"db://{rel_to_proj}"
            else:
                db_path = asset_abs.replace(os.sep, "/")

            friendly_type = _IMPORTER_TYPE_MAP.get(importer, importer)
            results.append({
                "uuid": uuid,
                "path": db_path,
                "name": stem,
                "type": friendly_type,
                "importer": importer,
            })
            if len(results) >= max_results:
                return {
                    "folder": folder, "count": len(results), "truncated": True,
                    "assets": results,
                    "hint": f"达上限 {max_results}, 收紧 name_pattern 或缩小 folder",
                }

    return {
        "folder": folder,
        "filterType": asset_type or None,
        "filterName": name_pattern or None,
        "count": len(results),
        "assets": results,
    }


# ── 同名节点查找 / uuid 查询与引用 ──────────────────────────────────────────

def find_nodes_by_name(
    asset_path: str,
    node_name: str,
    project_path: str = "",
    fuzzy: bool = False,
) -> Dict[str, Any]:
    """查找场景/prefab 中所有同名节点, 一同返回(不因重名报错)。

    fuzzy=True 时按名称子串匹配(大小写不敏感), 精确匹配优先。
    返 {assetPath, nodeName, count, nodes: [{path, index, active, components:[{type,index}]}]}。
    """
    abs_path = resolve_asset_path(asset_path, project_path)
    if not os.path.isfile(abs_path):
        return {"error": f"文件不存在: {abs_path}"}
    try:
        data = load_cocos_asset(abs_path)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"解析失败: {e}"}
    root_idx = find_root_index(data)
    if root_idx is None:
        return {"error": "未找到根节点"}

    exact: List[Dict[str, Any]] = []
    fuzzy_hits: List[Dict[str, Any]] = []
    nl = node_name.lower() if node_name else ""

    def walk(idx: int, parent_path: str):
        node = data[idx]
        if node.get("__type__") not in ("cc.Node", "cc.Scene"):
            return
        name = node.get("_name", "?")
        node_path = (parent_path + "/" + name) if parent_path else name
        if name == node_name:
            matches = exact
        elif fuzzy and nl and nl in name.lower():
            matches = fuzzy_hits
        else:
            matches = None
        if matches is not None:
            comps = []
            for comp_ref in node.get("_components", []) or []:
                cid = comp_ref.get("__id__")
                if cid is not None and 0 <= cid < len(data):
                    comps.append({"type": data[cid].get("__type__", "?"), "index": cid})
            matches.append({
                "path": node_path, "index": idx,
                "active": node.get("_active", True),
                "components": comps,
            })
        for child_ref in node.get("_children", []) or []:
            cid = child_ref.get("__id__")
            if cid is not None:
                walk(cid, node_path)

    walk(root_idx, "")
    nodes = exact if exact else fuzzy_hits
    return {
        "assetPath": asset_path,
        "nodeName": node_name,
        "fuzzy": bool(fuzzy and not exact),
        "count": len(nodes),
        "nodes": nodes,
    }


def find_nodes_in_tree(
    asset_path: str,
    node_name: str,
    project_path: str = "",
    fuzzy: bool = False,
    max_depth: int = 0,
) -> Dict[str, Any]:
    """跨嵌套 prefab 查找节点(基于解析后的节点树)。

    与 find_nodes_by_name 的区别: 后者只搜单文件; 本函数沿解析树递归,
    嵌套 prefab 实例的内容也命中。每个命中记录:
      - path:     解析树内完整路径(含嵌套层级)
      - file:     节点实际所在文件(嵌套 prefab 时为其 prefab 文件)
      - filePath: 节点在该文件内的路径(可传给 build_node_components 查详情)
    max_depth <= 0 = 不限深度(嵌套受 max_nest 限制)。
    """
    res = build_scene_tree(asset_path, max_depth=max_depth, project_path=project_path)
    if res.get("error"):
        return res
    uuid_index = _get_uuid_index(project_path) if project_path else {}
    root = res.get("root") or {}
    root_file = resolve_asset_path(asset_path, project_path)
    exact: List[Dict[str, Any]] = []
    fuzzy_hits: List[Dict[str, Any]] = []
    nl = node_name.lower() if node_name else ""

    def walk(node: Dict[str, Any], file_ctx: str, within_path: str):
        name = node.get("name", "?")
        nested_uuid = node.get("_nestedFromUuid", "")
        if nested_uuid and uuid_index.get(nested_uuid):
            # 进入嵌套 prefab: 文件上下文切换到 prefab 文件, 路径从根名重计
            file_ctx = uuid_index[nested_uuid]
            within_path = ""
        node_within = (within_path + "/" + name) if within_path else name
        if name == node_name:
            target = exact
        elif fuzzy and nl and nl in name.lower():
            target = fuzzy_hits
        else:
            target = None
        if target is not None:
            target.append({
                "path": node.get("path"),
                "file": file_ctx,
                "filePath": node_within,
                "active": node.get("active", True),
                "components": node.get("components", []),
            })
        for ch in node.get("children", []) or []:
            walk(ch, file_ctx, node_within)

    walk(root, root_file, "")
    nodes = exact if exact else fuzzy_hits
    return {
        "assetPath": asset_path,
        "nodeName": node_name,
        "fuzzy": bool(fuzzy and not exact),
        "crossFile": True,
        "count": len(nodes),
        "nodes": nodes,
    }


def lookup_uuid(project_path: str, uuid: str) -> Dict[str, Any]:
    """uuid → 资产文件: 路径 + 类型 + 内容摘要。

    基于 assets/ 下 .meta 的 uuid 索引(首次扫 ~1-2s, 缓存)。
    """
    if not project_path:
        return {"error": "需 project_path"}
    index = _get_uuid_index(project_path)
    path = index.get(uuid)
    if not path:
        return {"error": f"uuid 未找到: {uuid}", "hint": "uuid 索引基于 assets/ 下 .meta"}
    importer = ""
    try:
        with open(path + ".meta", "r", encoding="utf-8-sig") as f:
            meta = json.load(f)
        importer = meta.get("importer", "")
    except Exception:
        pass
    summary: Dict[str, Any] = {}
    if os.path.isfile(path):
        summary["size"] = os.path.getsize(path)
        ext = os.path.splitext(path)[1].lower()
        if ext in (".scene", ".prefab"):
            try:
                data = load_cocos_asset(path)
                summary["objects"] = len(data)
                root_idx = find_root_index(data)
                if root_idx is not None:
                    summary["rootName"] = data[root_idx].get("_name")
            except Exception:
                pass
    return {
        "uuid": uuid,
        "path": path,
        "importer": importer,
        "type": _IMPORTER_TYPE_MAP.get(importer, importer),
        "summary": summary,
    }


# 引用扫描覆盖的文本资产扩展名
_REF_TEXT_EXTS = {
    ".scene", ".prefab", ".meta", ".ts", ".js", ".json", ".effect", ".mtl",
    ".anim", ".plist", ".fnt", ".txt", ".md", ".yaml", ".yml",
}


def find_uuid_refs(project_path: str, uuid: str, max_results: int = 100,
                   structured: bool = True) -> Dict[str, Any]:
    """扫描项目 assets/ 下文本文件, 找引用该 uuid 的文件。

    对 .scene/.prefab(JSON 数组) 做**结构化**扫描: 把每个 __uuid__ 引用定位到
    节点路径/组件/属性(替代纯文本子串误报)。其他类型走文本子串计数。

    - structured=True: scene/prefab 输出 {path, count, nodes: [{nodePath, comp, prop, uuid}]}
    - 非 scene/prefab 或结构化解析失败 → 回退文本 {path, count}

    返 {uuid, count, refs: [{path, count, nodes?}]}。
    """
    if not project_path:
        return {"error": "需 project_path"}
    assets_dir = os.path.join(project_path, "assets")
    if not os.path.isdir(assets_dir):
        return {"error": f"assets 目录不存在: {assets_dir}"}
    refs: List[Dict[str, Any]] = []
    for root, dirs, files in os.walk(assets_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("Temp", "library")]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _REF_TEXT_EXTS:
                continue
            path = os.path.join(root, fname)
            try:
                if structured and ext in (".scene", ".prefab"):
                    node_refs = _structured_uuid_refs(path, uuid)
                    if node_refs is not None:
                        if node_refs:
                            refs.append({"path": path, "count": len(node_refs),
                                         "nodes": node_refs})
                            if len(refs) >= max_results:
                                return {"uuid": uuid, "count": len(refs), "truncated": True,
                                        "refs": refs, "structured": True}
                        continue
                # 文本子串计数(非 scene/prefab 或结构化失败回退)
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    content = f.read()
                cnt = content.count(uuid)
                if cnt:
                    refs.append({"path": path, "count": cnt})
                    if len(refs) >= max_results:
                        return {"uuid": uuid, "count": len(refs), "truncated": True,
                                "refs": refs, "structured": structured}
            except Exception:
                continue
    return {"uuid": uuid, "count": len(refs), "refs": refs, "structured": structured}


def _structured_uuid_refs(file_path: str, uuid: str) -> Optional[List[Dict[str, Any]]]:
    """scene/prefab JSON 内 __uuid__ 引用 → [{nodePath, comp, prop, uuid}]。

    返回 None 表示结构化失败(应回退文本); [] 表示解析成功但无该 uuid 引用。
    """
    try:
        data = load_cocos_asset(file_path)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    base_u = uuid.split("@", 1)[0]

    # 节点名索引 + 路径索引(报告用)
    name_of: Dict[int, str] = {}
    for i, o in enumerate(data):
        if isinstance(o, dict):
            name_of[i] = o.get("_name") or o.get("__type__") or "?"
    root_idx = find_root_index(data)
    path_index = _build_path_index(data, root_idx) if root_idx is not None else {}

    def node_path_of(idx: int) -> str:
        if not path_index:
            return name_of.get(idx, "?")
        # 反向: 数组下标 → 最近路径(非节点对象则用其宿主节点路径)
        if idx in path_index:
            return path_index[idx]
        # 找最近祖先节点路径
        best = ""
        for p, i in path_index.items():
            if i <= idx and (not best or i > path_index[best]):
                best = p
        return best or name_of.get(idx, "?")

    out: List[Dict[str, Any]] = []
    for i, o in enumerate(data):
        if not isinstance(o, dict):
            continue
        otype = o.get("__type__", "")
        # 遍历非内部字段找 __uuid__ 引用
        for k, v in o.items():
            if k.startswith("__") or not isinstance(v, dict):
                continue
            if "__uuid__" in v:
                u = v.get("__uuid__", "")
                if u == uuid or u.split("@", 1)[0] == base_u:
                    out.append({
                        "nodePath": node_path_of(i),
                        "comp": otype,
                        "prop": k,
                        "uuid": u,
                    })
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict) and "__uuid__" in item:
                        u = item.get("__uuid__", "")
                        if u == uuid or u.split("@", 1)[0] == base_u:
                            out.append({
                                "nodePath": node_path_of(i),
                                "comp": otype,
                                "prop": k,
                                "uuid": u,
                            })
    return out


# ── 压缩 uuid 编解码(引擎 decode-uuid.ts 算法) ───────────────────────────────

_BASE64_KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
_BASE64_VALUES = {c: i for i, c in enumerate(_BASE64_KEYS)}
_HEX = "0123456789abcdef"
# 36 位模板: dash 在 8,13,18,23 → 32 个 hex 槽位
_UUID_INDICES = [i for i in range(36) if i not in (8, 13, 18, 23)]


def decode_uuid(compressed: str) -> str:
    """压缩 uuid → 36 位完整 uuid。

    支持两种压缩格式(引擎 EditorExtends.UuidUtils):
    - 22 位(min=true, 引擎 decode-uuid.ts): 2 头字符 + 20 base64(30 hex)
    - 23 位(min=false, 脚本组件 __type__ 实际格式): 5 头 hex + 18 base64(27 hex)
      实测项目所有脚本组件 __type__ 均为 23 位(2026-08-16)
    - @后缀(子资产 id, 如 @6c48a / @f9941)保留
    - 无法识别时原样返回
    """
    base, sep, sub = compressed.partition("@")
    if len(base) == 22:
        tpl = list("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")  # dash 在 8,13,18,23
        tpl[0] = base[0]
        tpl[1] = base[1]
        j = 2
        for i in range(2, 22, 2):
            lhs = _BASE64_VALUES[base[i]]
            rhs = _BASE64_VALUES[base[i + 1]]
            tpl[_UUID_INDICES[j]] = _HEX[lhs >> 2]
            j += 1
            tpl[_UUID_INDICES[j]] = _HEX[((lhs & 3) << 2) | (rhs >> 4)]
            j += 1
            tpl[_UUID_INDICES[j]] = _HEX[rhs & 0xF]
            j += 1
        return "".join(tpl) + (sep + sub if sep else "")
    if len(base) == 23:
        # 5 头 hex 直接保留, 18 base64 → 27 hex
        try:
            hexes = base[:5]
            for i in range(5, 23, 2):
                lhs = _BASE64_VALUES[base[i]]
                rhs = _BASE64_VALUES[base[i + 1]]
                hexes += _HEX[lhs >> 2]
                hexes += _HEX[((lhs & 3) << 2) | (rhs >> 4)]
                hexes += _HEX[rhs & 0xF]
            full = (hexes[:8] + "-" + hexes[8:12] + "-" + hexes[12:16]
                    + "-" + hexes[16:20] + "-" + hexes[20:])
            return full + (sep + sub if sep else "")
        except (KeyError, ValueError):
            return compressed
    return compressed


def compress_uuid(full: str) -> str:
    """36 位完整 uuid → 22 位压缩 uuid(decode_uuid 22 位格式的逆运算)。

    - 前 2 hex 原样保留
    - 剩余 30 hex 按 3→2 拆成 10 组 12bit, 每组产出 2 个 base64 字符
    - @后缀保留; 非 36 位输入原样返回
    """
    base, sep, sub = full.partition("@")
    if len(base) != 36:
        return full
    hexchars = base.replace("-", "")  # 32 hex
    out = hexchars[:2]
    for i in range(2, 32, 3):
        v = int(hexchars[i:i + 3], 16)  # 12bit
        out += _BASE64_KEYS[v >> 6] + _BASE64_KEYS[v & 0x3F]
    return out + (sep + sub if sep else "")


def compress_uuid23(full: str) -> str:
    """36 位完整 uuid → 23 位压缩 uuid(脚本组件 __type__ 格式)。

    - 前 5 hex 原样保留
    - 剩余 27 hex 按 3→2 拆成 9 组 12bit, 每组产出 2 个 base64 字符
    - @后缀保留; 非 36 位输入原样返回
    """
    base, sep, sub = full.partition("@")
    if len(base) != 36:
        return full
    hexchars = base.replace("-", "")  # 32 hex
    out = hexchars[:5]
    for i in range(5, 32, 3):
        v = int(hexchars[i:i + 3], 16)  # 12bit
        out += _BASE64_KEYS[v >> 6] + _BASE64_KEYS[v & 0x3F]
    return out + (sep + sub if sep else "")


def uuid_convert(uuid: str) -> Dict[str, str]:
    """识别输入形态并双向转换。返 {input, kind, full, compressed, compressed23}。
    kind: compressed(22位) / compressed23(23位) / full(36位) / unknown。
    @ 子资产后缀允许存在且保留。"""
    base = uuid.split("@", 1)[0]
    if len(base) == 22:
        return {"kind": "compressed", "full": decode_uuid(uuid), "compressed": uuid,
                "compressed23": compress_uuid23(decode_uuid(uuid))}
    if len(base) == 23:
        full = decode_uuid(uuid)
        return {"kind": "compressed23", "full": full, "compressed": compress_uuid(full),
                "compressed23": uuid}
    if len(base) == 36 and base.count("-") == 4:
        return {"kind": "full", "full": uuid, "compressed": compress_uuid(uuid),
                "compressed23": compress_uuid23(uuid)}
    return {"kind": "unknown", "full": uuid, "compressed": uuid, "compressed23": uuid}


def resolve_script_component(comp_type: str, project_path: str = "",
                             uuid_index: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """脚本组件 __type__(23 位压缩 uuid) → 脚本资产定位。

    返 {script, name, path, uuid, missing}:
    - script: 脚本文件名(如 G3D_Layout.ts), 反查失败用原 __type__
    - missing: True = uuid 无法在项目内定位(旧引用/已删除脚本)
    """
    if not comp_type or comp_type.startswith("cc."):
        return {"script": comp_type, "missing": False}
    base = comp_type.split("@", 1)[0]
    if len(base) not in (22, 23):
        return {"script": comp_type, "missing": False}
    full = decode_uuid(comp_type)
    if not full or "-" not in full:
        return {"script": comp_type, "missing": False}
    idx = uuid_index if uuid_index is not None else (
        _get_uuid_index(project_path) if project_path else {})
    path = idx.get(full)
    if path:
        return {"script": os.path.basename(path), "name": os.path.splitext(os.path.basename(path))[0],
                "path": path, "uuid": full, "missing": False}
    return {"script": comp_type, "uuid": full, "missing": True}


# ── 紧凑序列化(尽最大可能压缩, 防上下文膨胀) ────────────────────────────────

def _node_detail(node: Dict[str, Any], include_nest: bool = True) -> str:
    """节点行详情: [组件类型](未展开子节点数)@嵌套prefab路径(不含名字)。

    组件显示: cc. 前缀去除; 脚本组件显示脚本文件名(G3D_Layout.ts),
    missing(项目内无对应脚本)标 ⚠ + 原始压缩 uuid 保留可查。
    """
    comps = node.get("components", []) or []
    comp_str = ""
    if comps:
        types = []
        for c in comps:
            t = c.get("type", "?")
            if c.get("script"):
                types.append(c["script"])  # 脚本文件名(G3D_Layout.ts)
            elif c.get("missing"):
                types.append(f"⚠{t}")     # 压缩 uuid 反查失败
            else:
                types.append(t[3:] if t.startswith("cc.") else t)
        comp_str = "[" + ",".join(types) + "]"
    children = node.get("children", []) or []
    cc = node.get("childCount", 0)
    more = f"({cc})" if cc > len(children) else ""
    nest = ""
    if include_nest:
        nested = node.get("_nestedPath", "")
        # 嵌套 prefab 路径只留文件名(如 @CardMJ.prefab), 省字符; 全路径可用 uuid 查询
        nest = f"@{nested.rsplit('/', 1)[-1]}" if nested else ""
    return f"{comp_str}{more}{nest}"


def _node_line(node: Dict[str, Any], include_nest: bool = True) -> str:
    """单节点行: [!]名称 + 详情。"""
    act = "" if node.get("active", True) else "!"
    return f"{act}{node.get('name', '?')}{_node_detail(node, include_nest=include_nest)}"


def tree_to_text(root: Dict[str, Any]) -> str:
    """节点树 → 紧凑文本树(去结构化, 最大压缩)。

    每行: [├─|└─][!]名称[组件类型列表](未展开子节点数)@嵌套prefab路径
    - 组件类型去 cc. 前缀(脚本组件 uuid 原样)
    - ! 前缀 = inactive 节点
    - (N) = 该层未展开的子节点数(深度截断处)
    - @path = 嵌套 prefab 实例来源(只留文件名)
    - 前向声明(2026-08-16): 树内出现 ≥2 次的 prefab 在顶部声明一次(完整结构),
      树内实例折叠为 `名称 ×N →@prefab` 引用, 不再重复展开
    - 实例新增内容(2026-08-16 增强): 实例根在宿主文件里的额外 _children
      (超出 prefab 原始内容)标记 ✚N, 独立一行并在其下展开新增节点
    """
    from collections import Counter
    # ── 第一遍: 全量统计实例数(含嵌套) → 定 declared 集合 ──
    prefab_count: Counter = Counter()
    prefab_example: Dict[str, Dict[str, Any]] = {}

    def count_all(node: Dict[str, Any]):
        nested = node.get("_nestedPath", "")
        if nested:
            prefab_count[nested] += 1
            prefab_example.setdefault(nested, node)
        for ch in node.get("children", []) or []:
            count_all(ch)

    count_all(root)
    declared = {p for p, c in prefab_count.items() if c >= 2}

    def is_declared(node: Dict[str, Any]) -> bool:
        return bool(node.get("_nestedPath")) and node["_nestedPath"] in declared

    # ── 第二遍: 直接引用计数 + 嵌套来源关系 ──
    # direct_count[p] = 树内"可见"的直接实例数(声明区内嵌套实例不重复计数)
    # 嵌套关系: 遍历声明区示例树时, 记录 declared prefab 内部引用了哪些 declared prefab
    direct_count: Counter = Counter()
    nested_in: Dict[str, set] = {}  # 外层 prefab → {内层 prefab}

    def scan_direct(node: Dict[str, Any], in_declared: str = ""):
        """统计直接引用: in_declared 非空 = 当前在某个 declared prefab 子树内。
        树内直接可见的实例(非 declared 内部)计入 direct_count;
        declared 内部嵌套的 declared 实例记录 nested_in 关系, 不重复计。
        """
        nested = node.get("_nestedPath", "")
        if nested:
            if not in_declared:
                direct_count[nested] += 1
            elif nested in declared and in_declared != nested:
                nested_in.setdefault(in_declared, set()).add(nested)
        # declared prefab 内部: 用示例节点做结构展示(不递归计数, 只记录嵌套关系)
        if nested and nested in declared and not in_declared:
            for ch in node.get("children", []) or []:
                scan_direct(ch, in_declared=nested)
            return
        for ch in node.get("children", []) or []:
            scan_direct(ch, in_declared=in_declared)

    scan_direct(root)

    def short(nested: str) -> str:
        return nested.rsplit("/", 1)[-1]

    def _emit_children(node: Dict[str, Any], prefix: str, out: List[str],
                       declared: set):
        """递归输出节点子级(声明区用): 完整展开非 declared, declared 折叠引用。"""
        children = node.get("children", []) or []
        for i, ch in enumerate(children):
            last = i == len(children) - 1
            if is_declared(ch):
                out.append(f"{prefix}{'└─' if last else '├─'}"
                           f"{ch.get('name', '?')} →@{short(ch['_nestedPath'])}")
            else:
                out.append(f"{prefix}{'└─' if last else '├─'}"
                           f"{_node_line(ch, include_nest=False)}")
                _emit_children(ch, prefix + ("  " if last else "│ "), out, declared)

    lines: List[str] = []
    if declared:
        lines.append("前向声明 (重复 prefab, 完整结构, 树内以引用展示):")
        # 先大后小排序: 外层容器先声明, 被包含者后声明(嵌套关系拓扑序)
        # depth[p] = prefab 的嵌套深度(0=直接挂场景/普通节点, 1=在某个 declared 内, ...)
        # 深度浅(外层)先声明; 同深度按直接引用数降序
        depth = {p: 0 for p in declared}
        changed = True
        while changed:
            changed = False
            for outer, inners in nested_in.items():
                for inner in inners:
                    if depth[inner] <= depth[outer]:
                        depth[inner] = depth[outer] + 1
                        changed = True
        for path in sorted(declared, key=lambda p: (depth.get(p, 0), -direct_count.get(p, 0))):
            ex = prefab_example[path]
            dc = direct_count.get(path, 0)
            tc = prefab_count[path]
            cnt_str = f"×{dc}"
            if tc != dc:
                cnt_str += f" (含嵌套 {tc})"
            lines.append(f"  @{short(path)} {cnt_str}: "
                         f"{_node_line(ex, include_nest=False)}")
            # 声明区展开 prefab 自身子节点(完整结构, 供树内引用)
            _emit_children(ex, "    ", lines, declared)
        lines.append("")

    def walk(node: Dict[str, Any], prefix: str, is_last: bool):
        children = node.get("children", []) or []
        # ── declared prefab 实例: 完全折叠(不展开其 children) ──
        if is_declared(node):
            extra = node.get("_nestedExtra", []) or []
            ref = f"→@{short(node['_nestedPath'])}"
            if extra:
                # 有新增内容: 独立一行 ✚N, 新增节点展开在下方
                lines.append(f"{prefix}{'└─' if is_last else '├─'}"
                             f"{node.get('name', '?')} ✚{len(extra)} {ref}")
                for i, x in enumerate(extra):
                    walk(x, prefix + ("  " if is_last else "│ "), i == len(extra) - 1)
            else:
                lines.append(f"{prefix}{'└─' if is_last else '├─'}"
                             f"{node.get('name', '?')} {ref}")
            return
        lines.append(f"{prefix}{'└─' if is_last else '├─'}{_node_line(node)}")
        i = 0
        while i < len(children):
            ch = children[i]
            # 连续 declared prefab 叶子/非叶子实例合并(无新增时)
            if is_declared(ch) and not ch.get("_nestedExtra"):
                j = i + 1
                while (j < len(children)
                       and is_declared(children[j])
                       and not children[j].get("_nestedExtra")
                       and children[j].get("_nestedPath") == ch["_nestedPath"]):
                    j += 1
                count = j - i
                if count > 1:
                    ref = f"→@{short(ch['_nestedPath'])}"
                    lines.append(f"{prefix}{'└─' if j == len(children) else '├─'}"
                                 f"{ch.get('name', '?')} ×{count} {ref}")
                    i = j
                    continue
            walk(ch, prefix + ("  " if is_last else "│ "), i == len(children) - 1)
            i += 1

    walk(root, "", True)
    return "\n".join(lines)


def node_compact(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """节点查询结果 → 紧凑结构(短键, 组件类型去 cc. 前缀)。

    每节点: {p: 路径, a: active, np: 节点属性, c: [{t: 类型, p: 属性, r: 绑定引用}]}
    """
    out: List[Dict[str, Any]] = []
    for n in nodes:
        comps = []
        for c in n.get("components", []):
            t = c.get("type", "?")
            comps.append({
                "t": t[3:] if t.startswith("cc.") else t,
                "p": c.get("properties", {}),
                "r": c.get("refs", []),
            })
        out.append({
            "p": n.get("path"),
            "a": n.get("active", True),
            "np": n.get("nodeProps", {}),
            "c": comps,
        })
    return out
