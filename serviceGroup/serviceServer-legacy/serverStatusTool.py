#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""serverStatusTool.py —— 服务器状态端点（系统指标 + 服务进程指标）CLI 桥接。

**为什么存在**：`GET /api/serverstatus/get` 的实现依赖 `psutil`（CPU / 内存 / 进程 /
线程 / 句柄 / 磁盘 / 网络 / 磁盘IO 采集）。Rust 侧重写等于自造一套系统指标采集并引入
`sysinfo` 之类的新依赖，故沿用本仓既有做法（U3 `luaDataTool.py` / U4 `assetTool.py`）：
**HTTP 面留在 Rust，指标采集留在 Python**。

**调用契约**（Rust `routes/serverstatus.rs` 以子进程调用）：
    python serverStatusTool.py <action>          # 参数：stdin 的 JSON 对象
    stdout（单行 JSON）:
        {"ok": true,  "body": {...}}                        # 成功，body = 原 Flask 响应体
        {"ok": false, "status": 400|500, "message": "..."}   # 失败，沿用原状态码与文案
    action ∈ snapshot

**与 legacy 的关系**：各 action 是 `CustomRoute/ServiceRoute.py` 的
`api_serverstatus_get` + `get_system_status()` + `get_python_process_status()` 的
**逐条搬运**（同样的字段名、同样的 psutil 取值口径）。有意差异四处：

  1. 入参来自 stdin、出参打印 JSON（而非 Flask `jsonify`）；
  2. **被观测进程由 payload 的 `pid` 指定** —— legacy 观测 Flask 自身 `os.getpid()`，
     而现在对外服务的是 Rust 前台，故由 Rust 侧传 `std::process::id()`（助手是短命
     子进程，观测自己毫无意义）；
  3. 响应键**仍叫 `python`** —— 契约兼容优先：这是 :5000 的对外响应形状，改名是破坏性变更；
     被观测者已从 Flask 进程换成 Rust 服务进程，故把**用户看得见的那处**改成「服务进程状态」
     （页面标题），键名不动并在 `h_snapshot` 处留注释；
  4. **全机线程数改「一次快照」而非逐进程累加** —— legacy 的
     `sum(p.num_threads() for p in process_iter())` 在 Windows 上每调一次 `num_threads()`
     就做一次全系统线程快照（本仓 `services.rs` 亦记「legacy psutil iter 慢源」），本机实测
     **11.9 秒**；而本页每 5 秒轮询一次，会直接把请求追尾（实测端点 12.6s，高负载下 50s）。
     改为单次 `TH32CS_SNAPTHREAD` 快照（实测 **0.15 秒**，同为 ~12400 条线程），**字段语义
     不变**；非 Windows 才退回 psutil 逐进程累加，并顺带逐进程容错（跳过读不到的进程）。

**采样顺序（不额外等待）**：先给目标进程打一次 `cpu_percent(None)` 底样，再用
`psutil.cpu_percent(interval=1)` 阻塞 1 秒取系统 CPU —— 这一秒**同时**作为目标进程的
采样窗口（末尾再读一次），两个 CPU 值落在同一窗口内，总耗时仍约 1 秒（与 legacy 相当）。
"""

import json
import os
import sys
import traceback

# stdout 必须 UTF-8（Windows 管道默认可能落 ANSI 代码页，中文会让 Rust 侧 JSON 解析失败）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))

IMPORT_ERROR = None
try:
    import psutil
except Exception as e:  # pragma: no cover - 环境问题分支
    IMPORT_ERROR = "%s: %s" % (type(e).__name__, e)


class BadRequest(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status
        self.message = message


def _system_status():
    """搬运 legacy `get_system_status()`：整机视角的 12 个字段。"""
    # interval=1 → 阻塞 1 秒取真实占用（也是下面目标进程 CPU 的采样窗口）
    cpu_percent = psutil.cpu_percent(interval=1)

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net_io = psutil.net_io_counters()
    disk_io = psutil.disk_io_counters()

    return {
        'cpu_percent': cpu_percent,
        'memory_used': memory.used,
        'memory_total': memory.total,
        'process_count': len(psutil.pids()),
        'thread_count': _total_thread_count(),
        'handle_count': 0,  # Windows 没有全局句柄数的直接 API（同 legacy）
        'disk_used': disk.used,
        'disk_total': disk.total,
        # 注意：legacy 把网卡/磁盘的**累计字节数**填进 *rate 字段（前端再加 "/s" 显示）。
        # 名不符实但口径如此，逐条搬运不改（改了会让页面数字量级突变）。
        'network_receive_rate': net_io.bytes_recv,
        'network_send_rate': net_io.bytes_sent,
        'disk_read_rate': disk_io.read_bytes,
        'disk_write_rate': disk_io.write_bytes,
    }


def _total_thread_count():
    """全机线程数（见模块头差异 4：Windows 走一次快照，别逐进程累加）。"""
    if os.name == 'nt':
        n = _win_total_threads()
        if n >= 0:
            return n
    # 回退：逐进程累加（慢，仅非 Windows / 快照失败时走）。逐进程容错：读不到的跳过。
    total = 0
    for p in psutil.process_iter():
        try:
            if p.is_running():
                total += p.num_threads()
        except Exception:
            continue
    return total


def _win_total_threads():
    """Windows: 单次 TH32CS_SNAPTHREAD 快照数线程；失败返 -1（由调用方回退 psutil）。"""
    TH32CS_SNAPTHREAD = 0x00000004
    INVALID_HANDLE_VALUE = 0xFFFFFFFFFFFFFFFF
    try:
        import ctypes
        import ctypes.wintypes as wt

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wt.DWORD),
                ("cntUsage", wt.DWORD),
                ("th32ThreadID", wt.DWORD),
                ("th32OwnerProcessID", wt.DWORD),
                ("tpBasePri", wt.LONG),
                ("tpDeltaPri", wt.LONG),
                ("dwFlags", wt.DWORD),
            ]

        k32 = ctypes.windll.kernel32
        # 必须显式声明: 默认 restype=c_int 会把 64 位 HANDLE 截断（真踩过）
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        k32.Thread32First.restype = wt.BOOL
        k32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
        k32.Thread32Next.restype = wt.BOOL
        k32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]

        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if not snap or snap == INVALID_HANDLE_VALUE:
            return -1
        try:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(THREADENTRY32)
            count = 0
            ok = k32.Thread32First(snap, ctypes.byref(entry))
            while ok:
                count += 1
                ok = k32.Thread32Next(snap, ctypes.byref(entry))
            return count
        finally:
            k32.CloseHandle(snap)
    except Exception:
        return -1


def _process_status(proc):
    """搬运 legacy `get_python_process_status()`：被观测进程视角的 12 个字段。

    `proc` 为 None（pid 缺失 / 进程已退出 / 无权限）时给零值而非抛错 —— 本页每 5 秒
    轮询，服务重启窗口内读不到自己是正常的，不该整屏报错。
    """
    memory_total = psutil.virtual_memory().total
    disk = psutil.disk_usage(os.getcwd())
    net_io = psutil.net_io_counters()

    base = {
        'cpu_percent': 0.0,
        'memory_used': 0,
        'memory_total': memory_total,
        'process_count': 0,
        'thread_count': 0,
        'handle_count': 0,
        'disk_used': disk.used,
        'disk_total': disk.total,
        # 同 legacy：进程自身没有可用的网络计数, 回落整机口径
        'network_receive_rate': net_io.bytes_recv,
        'network_send_rate': net_io.bytes_sent,
        'disk_read_rate': 0,
        'disk_write_rate': 0,
    }
    if proc is None:
        return base

    try:
        memory_used = proc.memory_info().rss
    except Exception:
        return base
    try:
        thread_count = proc.num_threads()
    except Exception:
        thread_count = 0
    try:
        # Windows only；其它平台无此属性（legacy 同样以 hasattr 兜零）
        handle_count = proc.num_handles()
    except Exception:
        handle_count = 0
    try:
        io = proc.io_counters()
        disk_read_rate, disk_write_rate = io.read_bytes, io.write_bytes
    except Exception:
        disk_read_rate, disk_write_rate = 0, 0

    out = dict(base)
    out.update({
        # 底样已在本函数调用前打过, 这里读的是那 1 秒窗口内的占用
        'cpu_percent': proc.cpu_percent(None),
        'memory_used': memory_used,
        'process_count': 1,
        'thread_count': thread_count,
        'handle_count': handle_count,
        'disk_read_rate': disk_read_rate,
        'disk_write_rate': disk_write_rate,
    })
    return out


def _resolve_pid(data):
    """取 payload 的 pid；缺失/非法 → None（由 _process_status 兜零值）。"""
    raw = data.get('pid')
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def h_snapshot(data):
    """组装 `{success, system, python}`（形状与键名均对齐 legacy）。

    键 `python` 是 legacy 契约名：被观测者现在是 Rust 服务进程（见模块头差异 2/3），
    但响应形状对外可见，改名属破坏性变更，故保留。
    """
    pid = _resolve_pid(data)

    proc = None
    if pid:
        try:
            proc = psutil.Process(pid)
            proc.cpu_percent(None)  # 打底样（首调恒 0.0）
        except Exception:
            proc = None

    system_data = _system_status()          # 内含 1 秒采样窗口
    return {
        'success': True,
        'system': system_data,
        'python': _process_status(proc),    # 键名沿用 legacy（契约兼容）; 值是服务进程指标
    }


HANDLERS = {
    "snapshot": (h_snapshot, "获取服务器状态失败"),
}


def main(argv):
    action = argv[1] if len(argv) > 1 else ""

    if IMPORT_ERROR:
        print(json.dumps({
            "ok": False,
            "status": 500,
            "message": ("serverStatusTool 环境不可用（缺依赖？）: %s；该脚本需 psutil"
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
