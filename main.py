#!/usr/bin/env python3
"""infoServer — pure ServiceGroup launcher (走法 A: 无 HTTP, 不占端口).

读 config.yaml → ServiceGroupManager.start_all → 阻塞等 SIGINT → stop_all。
host 不监听任何 TCP 端口; 所有子服务(含 parlanceChat) 由 config.yaml services 声明,
按 enabled 开关即装/卸 → 可拆卸性。

服务级控制面 (ServiceControlServer):
  host 虽无 HTTP, 但开一个跨平台控制 socket (multiprocessing.connection, 同 run.py 模式),
  供外部 agent (cwd-mcp) 查询托管服务清单 / 按端口重启单个子服务:
    services → ServiceGroupManager.status_all()   (每个托管子服务实时状态)
    restart  → 按 port 找服务 → svc.restart()      (stop+start, 不触发 auto_restart 计数)
  这是子服务的唯一权威所有者视图; run.py 只负责拉起本 host, 不管理子服务。
"""

import json
import logging
import os
import signal
import socket
import subprocess
import threading
import time
from multiprocessing.connection import Connection, Listener
from pathlib import Path
from typing import Any, Optional

import yaml

from service_manager import ServiceGroupManager, ManagedService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

SVC_CTL_PIPE_WIN = r"\\.\pipe\infoserver_svc"
SVC_CTL_SOCKET_POSIX = "/tmp/infoserver_svc.sock"

_ERR_PARSE = -32700
_ERR_METHOD_NOT_FOUND = -32601
_ERR_INTERNAL = -32603


def load_config() -> dict:
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        logger.warning("config.yaml not found, using defaults (no services)")
        return {"services": []}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _svc_ctl_address() -> tuple[str, str]:
    """返回 (address, family) for multiprocessing.connection.Listener."""
    if os.name == "nt":
        return (SVC_CTL_PIPE_WIN, "AF_PIPE")
    return (SVC_CTL_SOCKET_POSIX, "AF_UNIX")


class _MethodNotFound(Exception):
    pass


class ServiceControlServer:
    """JSON-RPC 控制面 — ServiceGroupManager 子服务级操作 (与 run.py ControlServer 同构).

    方法:
      services  → {"services": status_all()}   每个托管子服务实时状态 (含 disabled)
      restart   → {"port": N} → 按 port 找服务 → svc.restart() → {"ok","name","status","pid"}
                  (未知端口 / disabled / daemon managed=false → 结构化 error)
      swap_exe  → {"port": N} → svc.swap_exe() (热替换 .exe, 无 verify/回滚)
      update    → {"names"|"tags"} → 异步 svn update 编排 (停→svn up→启→探活→失败回滚)
      update_log → {"running", "last"}  最近一次 update 编排实时进度 + 结果
    """

    def __init__(self, svc_mgr: ServiceGroupManager):
        self.svc_mgr = svc_mgr
        self._listener: Optional[Listener] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._address, self._family = _svc_ctl_address()
        self._update_running = False  # svn update 异步编排锁 (防 reload/重复触发竞态)

    @property
    def address(self) -> str:
        return self._address

    def start(self):
        # Clear stale UDS file (posix only; Named Pipe is kernel-managed on win)
        if self._family == "AF_UNIX" and os.path.exists(self._address):
            try:
                os.unlink(self._address)
            except OSError:
                pass
        try:
            self._listener = Listener(self._address, family=self._family)
        except Exception as e:
            # 控制管道被占 = 另有 host 持有。不退出 (host 可能刚被 run.py 拉起,
            # 旧 host 尚未释放管道), 转后台每 10s 重试接管, 让最后存活的 host
            # 自动成为控制面所有者 (2026-08-19 双实例事故根因修复的接管侧)。
            logger.warning(
                "ServiceControlServer bind failed (%s): %s — retrying every 10s "
                "to take over the control pipe when the old host exits.",
                self._address, e,
            )
            retry = threading.Thread(
                target=self._retry_bind, name="svc-ctl-retry", daemon=True
            )
            retry.start()
            return
        self._bind_serve()

    def _bind_serve(self):
        """正式启动 accept loop (绑定成功后调用)。"""
        self._thread = threading.Thread(
            target=self._accept_loop, name="svc-ctl-accept", daemon=True
        )
        self._thread.start()
        logger.info("ServiceControlServer listening on %s", self._address)

    def _retry_bind(self):
        """绑定失败后的接管重试: 每 10s 重绑控制管道, 成功后启动 accept loop。"""
        while not self._stop.is_set():
            time.sleep(10)
            try:
                self._listener = Listener(self._address, family=self._family)
            except Exception:
                continue
            logger.info("ServiceControlServer acquired %s", self._address)
            self._bind_serve()
            return

    def stop(self):
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except (OSError, EOFError):
                break
            except Exception:
                if self._stop.is_set():
                    break
                continue
            t = threading.Thread(
                target=self._handle_conn, args=(conn,),
                name="svc-ctl-conn", daemon=True,
            )
            t.start()

    def _handle_conn(self, conn: Connection):
        try:
            while not self._stop.is_set():
                try:
                    raw = conn.recv()
                except (EOFError, OSError):
                    break
                response = self._handle_request(raw)
                if response is None:
                    continue
                try:
                    conn.send(response)
                except (OSError, BrokenPipeError):
                    break
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _handle_request(self, raw) -> Optional[dict]:
        if not isinstance(raw, dict):
            return self._error(None, _ERR_PARSE, "Expected JSON object")
        req_id = raw.get("id")
        method = raw.get("method")
        params = raw.get("params") or {}
        if not isinstance(method, str):
            return self._error(req_id, _ERR_PARSE, "Missing 'method'")
        try:
            result = self._dispatch(method, params)
        except _MethodNotFound:
            return self._error(req_id, _ERR_METHOD_NOT_FOUND,
                               f"Method not found: {method}")
        except Exception as e:
            logger.exception("ServiceControlServer dispatch error: %s", e)
            return self._error(req_id, _ERR_INTERNAL, str(e))
        if req_id is None:
            return None  # JSON-RPC notification → no response
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "services":
            return {"services": self.svc_mgr.status_all()}
        if method == "restart":
            return self._restart_by_port(params.get("port"))
        if method == "swap_exe":
            return self._swap_exe_by_port(params.get("port"))
        if method == "stop":
            return self._stop_by_port(params.get("port"))
        if method == "start":
            return self._start_by_port(params.get("port"))
        if method == "update":
            return self._update_services(params.get("names") or params.get("tags"))
        if method == "update_log":
            return self._update_log()
        raise _MethodNotFound(method)

    def _restart_by_port(self, port) -> dict[str, Any]:
        if self._update_running:
            return {"error": "svn update in progress, restart blocked"}
        if port is None:
            return {"error": "port required"}
        svc: Optional[ManagedService] = self._find_by_port(int(port))
        if svc is None:
            return {"error": f"no managed service on port {port}"}
        if not svc.enabled:
            return {"error": f"service '{svc.name}' on port {port} is disabled (enabled=false)"}
        if not svc.managed:
            return {"error": f"service '{svc.name}' on port {port} is daemon (managed=false), restart not supported"}
        svc.restart(timeout=15)
        return {
            "ok": True,
            "name": svc.name,
            "port": svc.port,
            "status": svc.status,
            "pid": svc.pid,
        }

    def _swap_exe_by_port(self, port) -> dict[str, Any]:
        if self._update_running:
            return {"error": "svn update in progress, swap_exe blocked"}
        if port is None:
            return {"error": "port required"}
        svc: Optional[ManagedService] = self._find_by_port(int(port))
        if svc is None:
            return {"error": f"no managed service on port {port}"}
        if not svc.enabled:
            return {"error": f"service '{svc.name}' on port {port} is disabled (enabled=false)"}
        if not svc.managed:
            return {"error": f"service '{svc.name}' on port {port} is daemon (managed=false)"}
        result = svc.swap_exe()
        result.setdefault("name", svc.name)
        result.setdefault("port", svc.port)
        return result

    def _find_by_port(self, port: int) -> Optional[ManagedService]:
        for svc in self.svc_mgr.services:
            if svc.port == port:
                return svc
        return None

    def _stop_by_port(self, port) -> dict[str, Any]:
        """单服务停止原语 (供 cwd_infoserver_build_swap 停→build→start 编排解锁 exe)."""
        if self._update_running:
            return {"error": "svn update in progress, stop blocked"}
        if port is None:
            return {"error": "port required"}
        svc: Optional[ManagedService] = self._find_by_port(int(port))
        if svc is None:
            return {"error": f"no managed service on port {port}"}
        if not svc.enabled:
            return {"error": f"service '{svc.name}' on port {port} is disabled (enabled=false)"}
        if not svc.managed:
            return {"error": f"service '{svc.name}' on port {port} is daemon (managed=false), stop not supported"}
        if not svc.running:
            return {"ok": True, "name": svc.name, "port": svc.port, "status": svc.status, "note": "not running"}
        svc.stop(timeout=15)
        return {"ok": True, "name": svc.name, "port": svc.port, "status": svc.status}

    def _start_by_port(self, port) -> dict[str, Any]:
        """单服务启动原语 (供 build_swap 停→build→start 编排; 已运行则幂等)."""
        if self._update_running:
            return {"error": "svn update in progress, start blocked"}
        if port is None:
            return {"error": "port required"}
        svc: Optional[ManagedService] = self._find_by_port(int(port))
        if svc is None:
            return {"error": f"no managed service on port {port}"}
        if not svc.enabled:
            return {"error": f"service '{svc.name}' on port {port} is disabled (enabled=false)"}
        if not svc.managed:
            return {"error": f"service '{svc.name}' on port {port} is daemon (managed=false)"}
        if svc.running:
            return {"ok": True, "name": svc.name, "port": svc.port, "status": svc.status, "note": "already running"}
        svc.start()
        return {"ok": True, "name": svc.name, "port": svc.port, "status": svc.status}

    # ── update 编排: 停指定子服务 → svn update → 启 ─────────────────────
    # 用户方案: infoServer 提供断点, 请求后先停两个 serviceServer 子服务
    # (解锁 exe), 然后更新 svn, 更新完毕后启动两个子服务。
    # svn 工作副本根 = infoServer 目录本身 (.svn 在根), 用 svn info 动态定位,
    # 天然覆盖 serviceGroup 下两子服务, 不依赖每服务声明 svn 路径。

    _UPDATE_DEFAULT_NAMES = ["serviceServer-rust", "serviceServer-legacy"]

    def _update_services(self, names=None):
        """触发异步 svn update 编排 (停 targets → svn up → 启 targets → 写日志)。
        立即返「已触发」, 编排在后台 thread 跑 (调用方 legacy/rust 是被停目标, 需先返响应)。
        """
        if self._update_running:
            return {"error": "update already running, poll update_log to wait finish"}
        if names is None:
            names = self._UPDATE_DEFAULT_NAMES
        targets = []
        for n in names:
            svc = self.svc_mgr.get(n)
            if svc is None:
                return {"error": f"no managed service named '{n}'"}
            if not svc.enabled:
                return {"error": f"service '{n}' is disabled (enabled=false)"}
            if not svc.managed:
                return {"error": f"service '{n}' is daemon (managed=false), cannot orchestrate"}
            targets.append(svc)

        self._update_running = True
        log_path = os.path.join(os.getcwd(), "svn_update.log")
        t = threading.Thread(
            target=self._update_async,
            args=(targets, log_path),
            name="svc-update",
            daemon=True,
        )
        t.start()
        return {
            "ok": True,
            "message": "update triggered (async), poll update_log for result",
            "log": log_path,
            "names": [s.name for s in targets],
        }

    def _update_async(self, targets, log_path):
        """后台编排: sleep 1.5s (让调用方响应先发) → 停 → svn up → 启 → 探活 → 失败自动回滚。
        每关键节点把 record 写 log_path (update_log 实时可见), finally 解锁 (防卡死)。
        关键节点必有日志: 停完成 / svn update 结果 / 启完成 / 探活结果 / 回滚各步。
        """
        try:
            time.sleep(1.5)
            record = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "names": [s.name for s in targets],
                "stage": "start",
            }
            # 0) svn 工作副本根 + 更新前 revision (回滚基准)
            svn_root = self._svn_working_copy_root()
            rev_before = self._svn_revision(svn_root)
            record["working_copy_root"] = svn_root
            record["revision_before"] = rev_before
            logger.info("[update] svn working copy root=%s, current rev=%s", svn_root, rev_before)

            # 0.5) 工作副本干净性防护: 有本地改动(M/?/conflict)则中止, 防 svn up 卷进 dev 未提交现场
            dirty = self._svn_working_copy_dirty(svn_root)
            record["dirty_check"] = dirty
            record["stage"] = "dirty_checked"
            self._write_update_record(log_path, record)
            if dirty:
                logger.warning("[update] svn working copy dirty, aborting: %s", dirty)
                record["ok"] = False
                record["error"] = f"svn working copy dirty, abort before update: {dirty}"
                record["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                record["stage"] = "aborted_dirty"
                self._write_update_record(log_path, record)
                return

            # 1) 停服务解锁 exe / py 源码
            stopped = []
            for svc in targets:
                svc.stop(timeout=15)
                stopped.append({"name": svc.name, "status": svc.status, "pid": svc.pid})
            record["stopped"] = stopped
            record["stage"] = "stopped"
            self._write_update_record(log_path, record)
            logger.info("[update] stopped %s", ", ".join(s.name for s in targets))

            # 2) svn update (cwd = svn 工作副本根)
            svn_out, svn_err, svn_rc = self._run_svn_update(svn_root)
            rev_after = self._svn_revision(svn_root)
            record["svn"] = {
                "ok": svn_rc == 0,
                "working_copy_root": svn_root,
                "returncode": svn_rc,
                "stdout": svn_out,
                "stderr": svn_err,
                "revision_after": rev_after,
            }
            record["stage"] = "svn_updated"
            self._write_update_record(log_path, record)
            logger.info("[update] svn update rc=%d (rev %s -> %s)", svn_rc, rev_before, rev_after)

            # 3) 启服务
            started = []
            for svc in targets:
                svc.start()
                started.append({"name": svc.name, "status": svc.status, "pid": svc.pid})
            record["started"] = started
            record["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            record["stage"] = "started"
            self._write_update_record(log_path, record)
            logger.info("[update] started %s, probing listening (30s)", ", ".join(s.name for s in targets))

            # 4) 探活 listening (30s 超时)
            probe_ok, probe_detail = self._probe_all(targets, timeout=30)
            record["probe"] = probe_detail
            record["stage"] = "probed"
            self._write_update_record(log_path, record)
            logger.info("[update] probe ok=%s %s", probe_ok, probe_detail.get("services"))

            # 5) 失败自动回滚: svn update -r <旧rev> → 重启 → 再探活
            if svn_rc == 0 and not probe_ok and rev_before:
                self._rollback(targets, rev_before, svn_root, record, log_path)
                record["stage"] = "rolled_back"
                record["ok"] = False  # 本次更新失败, 已回滚
                self._write_update_record(log_path, record)
            else:
                record["rollback"] = {"needed": False}
                record["ok"] = (svn_rc == 0) and probe_ok

            record["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            record["stage"] = "done"
            self._write_update_record(log_path, record)
            logger.info("[update] finished (ok=%s), log: %s", record["ok"], log_path)
        except Exception as e:
            logger.exception("svn update async failed: %s", e)
            self._write_update_record(log_path, {"ok": False, "error": str(e),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": "error"})
        finally:
            self._update_running = False

    def _update_log(self):
        """返最近一次 update 编排状态 + 日志 (供前端轮询 / 排错)。"""
        log_path = os.path.join(os.getcwd(), "svn_update.log")
        result = {"running": self._update_running}
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    result["last"] = json.load(f)
            except Exception as e:
                result["error"] = f"read log failed: {e}"
        else:
            result["message"] = "no update log yet"
        return result

    def _svn_working_copy_root(self) -> Optional[str]:
        """svn info 取 Working Copy Root Path (infoServer 根 = 工作副本根)."""
        try:
            r = subprocess.run(
                ["svn", "info", "--non-interactive"],
                capture_output=True, text=True, timeout=30,
                cwd=os.getcwd(),
            )
            for line in (r.stdout or "").splitlines():
                if line.startswith("Working Copy Root Path:"):
                    return line.split(":", 1)[1].strip()
        except Exception as e:
            logger.warning("svn info failed: %s", e)
        return None

    def _run_svn_update(self, cwd: Optional[str]):
        """svn update --non-interactive, 返回 (stdout, stderr, returncode)."""
        return self._run_svn(["--non-interactive"], cwd)

    def _run_svn_update_rev(self, cwd: Optional[str], revision):
        """svn update -r <rev> --non-interactive (回滚), 返回 (stdout, stderr, returncode)."""
        return self._run_svn(["-r", str(revision), "--non-interactive"], cwd)

    def _run_svn(self, args, cwd: Optional[str]):
        """通用 svn 调用, gbk 编码, 120s 超时, 返回 (stdout, stderr, returncode)."""
        try:
            r = subprocess.run(
                ["svn", "update", *args],
                capture_output=True, text=True, timeout=120, cwd=cwd or os.getcwd(),
                encoding="gbk", errors="replace",
            )
            return (r.stdout or "").strip(), (r.stderr or "").strip(), r.returncode
        except subprocess.TimeoutExpired:
            return "", "svn update timed out after 120s", -1
        except FileNotFoundError:
            return "", "svn CLI not found", -1
        except Exception as e:
            return "", str(e), -1

    def _svn_revision(self, cwd: Optional[str]) -> Optional[str]:
        """svn info 取工作副本当前 Revision (更新前/后各自取值, 回滚基准)."""
        try:
            r = subprocess.run(
                ["svn", "info", "--non-interactive"],
                capture_output=True, text=True, timeout=30,
                cwd=cwd or os.getcwd(),
            )
            for line in (r.stdout or "").splitlines():
                if line.startswith("Revision:"):
                    return line.split(":", 1)[1].strip()
        except Exception as e:
            logger.warning("svn info revision failed: %s", e)
        return None

    def _svn_working_copy_dirty(self, cwd: Optional[str]) -> str:
        """检查 svn 工作副本是否有阻断 svn update 的冲突。

        返 '' = 可更新; 非空 = 需先处理的冲突摘要 (如 "D     C path").
        只挡 C (tree conflict 第七列 / 内容冲突第一列) — svn update 唯一会直接
        失败的本地状态。本地修改 M / 新增 A / 删除 D / 未版本化 ? / missing !,
        svn update 均安全处理 (merge / 恢复, 不丢数据), 一律放行。生产环境
        config.yaml 等本地专属配置改动是常态, 挡 M 会让自动更新永远卡住。
        """
        try:
            r = subprocess.run(
                ["svn", "status"],
                capture_output=True, text=True, timeout=30,
                cwd=cwd or os.getcwd(),
                encoding="gbk", errors="replace",
            )
            lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
            if not lines:
                return ""
            parts = []
            for ln in lines:
                s = ln.strip()
                # tree conflict 落在第七列 (行前 8 字符内 'C'), 内容冲突第一列也是 'C'
                if "C" in ln[:8]:
                    parts.append(s)
            if not parts:
                return ""
            shown = parts[:10]
            extra = f"... (+{len(parts)-10} more)" if len(parts) > 10 else ""
            return "; ".join(shown) + extra
        except Exception as e:
            return f"svn status failed: {e}"

    def _probe_svc(self, svc: ManagedService, timeout: float = 0.5) -> bool:
        """探活单个子服务: 进程存活 + (有端口) 端口 listening."""
        if not svc.running:
            return False
        if not svc.port:
            return True  # 无端口 → 进程存活即视为就绪
        try:
            with socket.create_connection(("127.0.0.1", svc.port), timeout=timeout):
                return True
        except OSError:
            return False

    def _probe_all(self, targets, timeout: float = 30):
        """探活全部 targets (30s 超时), 返 (ok, detail).
        detail: {ok, timeout, services: [{name, port, listening}]} (关键节点日志用).
        """
        results = {svc.name: False for svc in targets}
        deadline = time.time() + timeout
        while time.time() < deadline:
            all_ok = True
            for svc in targets:
                if results[svc.name]:
                    continue
                if self._probe_svc(svc):
                    results[svc.name] = True
                else:
                    all_ok = False
            if all_ok:
                break
            time.sleep(1)
        detail = {
            "ok": all(results.values()),
            "timeout": timeout,
            "services": [{"name": svc.name, "port": svc.port,
                          "listening": results[svc.name]} for svc in targets],
        }
        return detail["ok"], detail

    def _rollback(self, targets, revision, svn_root, record, log_path):
        """回滚: 停(杀坏 exe 崩溃循环) → svn update -r <旧rev> → 重启 → 再探活。
        每关键节点写 log_path (update_log 实时可见)。返 rollback detail dict。
        """
        logger.warning("[update] probe failed, rolling back to svn r%s", revision)
        detail = {"needed": True, "revision": revision}
        # a) 停 (坏 exe 可能正在跑/crash-loop, 先停解锁)
        stopped = []
        for svc in targets:
            if svc.running:
                svc.stop(timeout=15)
            stopped.append({"name": svc.name, "status": svc.status, "pid": svc.pid})
        detail["stopped"] = stopped
        record["rollback"] = detail
        record["stage"] = "rollback_stopped"
        self._write_update_record(log_path, record)
        # b) svn update -r <旧rev>
        out, err, rc = self._run_svn_update_rev(svn_root, revision)
        detail["svn"] = {"ok": rc == 0, "revision": revision, "returncode": rc,
                         "stdout": out, "stderr": err}
        record["rollback"] = detail
        record["stage"] = "rollback_svn"
        self._write_update_record(log_path, record)
        logger.info("[update] rollback svn -r %s rc=%d", revision, rc)
        # c) 重启
        restarted = []
        for svc in targets:
            svc.start()
            restarted.append({"name": svc.name, "status": svc.status, "pid": svc.pid})
        detail["restarted"] = restarted
        record["rollback"] = detail
        record["stage"] = "rollback_started"
        self._write_update_record(log_path, record)
        # d) 再探活
        probe_ok, probe_detail = self._probe_all(targets, timeout=30)
        detail["probe_after"] = probe_detail
        detail["ok"] = probe_ok
        record["rollback"] = detail
        record["stage"] = "rollback_probed"
        self._write_update_record(log_path, record)
        logger.warning("[update] rollback restart probe ok=%s", probe_ok)
        return detail

    def _write_update_record(self, log_path, record):
        """把当前 record 写 svn_update.log (update_log 实时可见, 关键节点刷新)."""
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("write %s failed: %s", log_path, e)

    @staticmethod
    def _error(req_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}


def main():
    config = load_config()

    svc_mgr = ServiceGroupManager(config.get("services") or [])
    svc_mgr.start_all()

    ctl = ServiceControlServer(svc_mgr)
    ctl.start()

    # 阻塞等信号; ServiceGroupManager 监控线程是 daemon, 主线程必须存活
    stop_event = threading.Event()

    def _on_signal(signum, frame):
        logger.info("Signal %d received, shutting down ServiceGroup", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    # Windows 仅 SIGINT 可达; SIGTERM 仅 POSIX 注册
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _on_signal)
        except (ValueError, OSError):
            pass

    logger.info("ServiceGroup launcher running (no HTTP). Ctrl+C to stop.")
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        ctl.stop()
        svc_mgr.stop_all()
        logger.info("Launcher shut down")


if __name__ == "__main__":
    main()
