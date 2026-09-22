#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cpDataTool.py — CP 用户数据（直连 MySQL + redis db10）CLI 桥接。

**为什么存在**：deposit 页「CP 数据」tab 的 6 个端点原实现在 legacy
`CustomRoute/CpDirectRoute.py`。本文件把**数据层**（`CommonTools/xzmpDB/CpUserData.py`：
凭据解密 + mysql/redis 连接 + 受控写纪律）留在 Python，把 **HTTP 面留给 Rust**
（`routes/cp_data.rs`）—— 与 `luaDataTool.py` / `assetTool.py` / `serverStatusTool.py`
同一范式：Rust 侧不引 mysql/redis 依赖，也不二次实现凭据解密与业务逻辑。

**调用契约**（Rust `routes/cp_data.rs` 以子进程调用）：

    python cpDataTool.py <action>        # 参数：stdin 的 JSON 对象
    stdout（单行 JSON）：
        {"ok": true,  "body": {...}}                       # 成功，body = 原 Flask 响应体
        {"ok": false, "status": 400|500, "message": "..."}  # 失败，沿用原状态码与文案

    action ∈ appcodes | modules | module | write-prepare | write | clear

**与 legacy 的关系**：各 action 是 `CpDirectRoute.py` 同名端点的**逐条搬运**（校验文案、
状态码、数据调用序列一致；`ValueError` → 400，其它异常 → 500 带各端点前缀），唯一差异是
「入参来自 stdin」而非 `request.json`、「出参打印 JSON」而非 `jsonify`。

**参数校验分工**：需求侧的**廉价校验**（字段存在性、正整数、范围、标识符白名单）由 Rust 侧
先行拦截并返回**同样文案**；本文件仍保留原样校验作为兜底（直接调用本脚本时行为与原
Flask 路由一致）。

**安全边界**：本工具连的是 **CP 平台真库**（MySQL `modsvr283db` @ 阿里云 RDS + redis
db10）—— `write` / `clear` 会**真改/真删玩家数据**（`commit_write` 写前取快照随响应返回，
可原样回灌撤回；`clear` 不可逆）。调用前请确认目标 uid。
"""
import json
import os
import sys
import traceback

# stdout 必须是 UTF-8：调用方（Rust）按 UTF-8 解析 JSON，而 Windows 管道默认可能落到
# ANSI 代码页（实测 cp936），中文文案会变成非 UTF-8 字节导致解析失败。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - 老解释器/异常环境
    pass

# 让 `CommonTools.*` 可被导入（子进程 cwd 未必是本目录）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 数据层依赖：缺依赖时不直接崩，留成 JSON 错误让 Rust 侧能转成可读文案
IMPORT_ERROR = None
try:
    from CommonTools.xzmpDB import CpUserData
except Exception as e:  # pragma: no cover - 环境问题分支
    IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)

MAX_USERID = 2 ** 31 - 1


class BadRequest(Exception):
    """携带原 400 文案与状态码的校验失败。"""

    def __init__(self, message, status=400):
        super(BadRequest, self).__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- 校验（同 CpDirectRoute）

def _parse_userid(raw):
    """解析并校验玩家ID（文案与 CpDirectRoute._parse_userid 一致）。"""
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        raise BadRequest('玩家ID格式错误')
    if uid <= 0 or uid > MAX_USERID:
        raise BadRequest('玩家ID超出范围')
    return uid


def _parse_appcode(raw):
    """解析并校验缩写（仅小写字母/数字/下划线）。"""
    appcode = (raw or '').strip().lower()
    if not appcode:
        raise BadRequest('缩写不能为空')
    if not CpUserData._IDENT_RE.match(appcode):  # noqa: SLF001 —— 复用同一套标识符白名单
        raise BadRequest('缩写格式错误（仅小写字母/数字/下划线）')
    return appcode


def _parse_module(raw):
    """解析并校验模块名（复用同一套标识符白名单）。"""
    module = (raw or '').strip().lower()
    if not CpUserData._IDENT_RE.match(module):  # noqa: SLF001
        raise BadRequest('模块名非法: %s' % module)
    return module


# ---------------------------------------------------------------- 各 action

def h_appcodes(data):
    """可用缩写清单（从落盘表名派生）。无参数。"""
    return {'success': True, 'data': {'appcodes': CpUserData.list_appcodes()}}


def h_modules(data):
    """按 玩家ID + 缩写 列该玩家相关模块（redis 与 mysql 的并集）。"""
    uid = _parse_userid(data.get('userid'))
    appcode = _parse_appcode(data.get('appcode'))
    return {'success': True, 'data': CpUserData.list_modules(uid, appcode)}


def h_module(data):
    """点开单个模块：列出其 redis 与 mysql 明细。"""
    uid = _parse_userid(data.get('userid'))
    appcode = _parse_appcode(data.get('appcode'))
    module = _parse_module(data.get('module'))
    return {'success': True, 'data': CpUserData.module_detail(uid, appcode, module)}


def h_write_prepare(data):
    """受控写第一步：写前实时查询，回吐当前值作为编辑起点（只读，不改数据）。"""
    uid = _parse_userid(data.get('userid'))
    appcode = _parse_appcode(data.get('appcode'))
    module = _parse_module(data.get('module'))
    try:
        return {'success': True, 'data': CpUserData.prepare_write(
            uid, appcode, module,
            redis_key=(data.get('redisKey') or None),
            mysql_name=(data.get('mysqlName') or None))}
    except ValueError as e:
        raise BadRequest(str(e))


def h_write(data):
    """受控写第二步：写入（存在即写 —— 两侧都在则双写，只剩一侧则只写该侧）。

    ⚠ 会真实修改玩家数据；响应含 `snapshot`，原样回灌本 action 即可撤回。
    """
    uid = _parse_userid(data.get('userid'))
    appcode = _parse_appcode(data.get('appcode'))
    module = _parse_module(data.get('module'))
    if 'value' not in data:
        raise BadRequest('缺少 value')
    try:
        return {'success': True, 'data': CpUserData.commit_write(
            uid, appcode, module, data.get('value'),
            redis_key=(data.get('redisKey') or None),
            mysql_name=(data.get('mysqlName') or None))}
    except ValueError as e:
        raise BadRequest(str(e))


def h_clear(data):
    """清空该玩家该模块的数据（redis key 与 mysql 行两侧都清）。⚠ 不可逆、无快照。"""
    uid = _parse_userid(data.get('userid'))
    appcode = _parse_appcode(data.get('appcode'))
    module = _parse_module(data.get('module'))
    try:
        return {'success': True, 'data': CpUserData.clear_module(uid, appcode, module)}
    except ValueError as e:
        raise BadRequest(str(e))


# action -> (handler, 未预期异常时的文案前缀)
# 前缀与 CpDirectRoute 各端点的 `except Exception` 分支逐字一致
HANDLERS = {
    'appcodes': (h_appcodes, '缩写清单获取失败'),
    'modules': (h_modules, '模块查询失败'),
    'module': (h_module, '模块详情查询失败'),
    'write-prepare': (h_write_prepare, '写入前查询失败'),
    'write': (h_write, '写入失败'),
    'clear': (h_clear, '清空失败'),
}


def main(argv):
    action = argv[1] if len(argv) > 1 else ""

    if IMPORT_ERROR:
        print(json.dumps({
            "ok": False,
            "status": 500,
            "message": ("cpDataTool 环境不可用（缺依赖？: %s）。"
                        "该脚本必须用带 mysql/redis 的解释器运行"
                        "（Rust 侧可用环境变量 SERVICESVR_PYTHON 指定）。" % IMPORT_ERROR),
        }, ensure_ascii=False))
        return 0

    entry = HANDLERS.get(action)
    if entry is None:
        print(json.dumps({
            "ok": False,
            "status": 400,
            "message": "不支持的动作: %s（可选: %s）" % (action, ", ".join(sorted(HANDLERS))),
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
        print(json.dumps({
            "ok": False, "status": 400, "message": "参数 JSON 解析失败: %s" % e,
        }, ensure_ascii=False))
        return 0

    try:
        body = handler(data)
        print(json.dumps({"ok": True, "body": body}, ensure_ascii=False))
    except BadRequest as e:
        print(json.dumps({"ok": False, "status": e.status, "message": e.message}, ensure_ascii=False))
    except Exception as e:
        # 对应 legacy 各端点的 `except Exception` 分支：500 + "<动作>失败: <e>"
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({
            "ok": False, "status": 500, "message": "%s: %s" % (err_prefix, e),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
