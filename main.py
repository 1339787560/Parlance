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

import logging
import os
import signal
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
    """

    def __init__(self, svc_mgr: ServiceGroupManager):
        self.svc_mgr = svc_mgr
        self._listener: Optional[Listener] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._address, self._family = _svc_ctl_address()

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
            logger.warning("ServiceControlServer bind failed (%s): %s", self._address, e)
            return
        self._thread = threading.Thread(
            target=self._accept_loop, name="svc-ctl-accept", daemon=True
        )
        self._thread.start()
        logger.info("ServiceControlServer listening on %s", self._address)

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
        raise _MethodNotFound(method)

    def _restart_by_port(self, port) -> dict[str, Any]:
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

    def _find_by_port(self, port: int) -> Optional[ManagedService]:
        for svc in self.svc_mgr.services:
            if svc.port == port:
                return svc
        return None

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
