#!/usr/bin/env python3
"""Interactive foreground launcher for infoServer.

Usage:
    python run.py            # Start infoServer and listen for hotkeys
    python run.py --no-input # Start without keyboard listener (service mode)

Hotkeys:
    r / R   Reload infoServer (stop fully then start)
    q / Q   Stop service and quit launcher
    s / S   Show current status
    h / H   Show this help
"""

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Connection, Listener
from pathlib import Path
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run")

import yaml
from service_manager import ManagedService

if os.name == "nt":
    import msvcrt
else:
    msvcrt = None

if os.name != "nt":
    import signal
    import tty
    import termios

PROJECT_DIR = Path(__file__).resolve().parent


# ── Control surface ──────────────────────────────────────────────────
# Cross-platform control socket: lets external agents (e.g. Claude Code)
# drive reload/quit/status WITHOUT sharing the keyboard loop's tty stdin.
#
# Wire  : multiprocessing.connection (length-prefixed pickle frame).
# Msg   : JSON-RPC 2.0 dict shape (method/id/params/result/error).
# Client: ctl_client.py (Python CLI front-end).
#
# Coexists with keyboard loop — both run as independent daemon threads.
# Security: local trusted IPC only. Any local process can connect; do NOT
# expose this socket across hosts.

CTL_PIPE_WIN = r"\\.\pipe\infoserver_ctl"
CTL_SOCKET_POSIX = "/tmp/infoserver_ctl.sock"

_ERR_PARSE = -32700
_ERR_METHOD_NOT_FOUND = -32601
_ERR_INTERNAL = -32603


def _ctl_address():
    """Return (address, family) for the control socket on this platform."""
    if os.name == "nt":
        return (CTL_PIPE_WIN, "AF_PIPE")
    return (CTL_SOCKET_POSIX, "AF_UNIX")


class _MethodNotFound(Exception):
    pass


class ControlServer:
    """JSON-RPC control server, coexisting with the Launcher keyboard loop."""

    def __init__(self, launcher: "Launcher"):
        self.launcher = launcher
        self._listener: Optional[Listener] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._address, self._family = _ctl_address()

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
            # 单实例锁: 控制管道被占 = 已有 launcher 在跑。直接退出, 让已有实例
            # 独占服务 (2026-08-19 双实例事故根因: 第二套实例静默降级继续跑,
            # 导致 cwd-mcp 状态视图失真 + 端口互相抢占)。
            logger.error(
                "Control pipe %s already in use (%s) — another infoServer launcher "
                "is running; exiting to keep single instance.",
                self._address, e,
            )
            raise SystemExit(1)
        self._thread = threading.Thread(
            target=self._accept_loop, name="ctl-accept", daemon=True
        )
        self._thread.start()
        logger.info("ControlServer listening on %s", self._address)

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
                name="ctl-conn", daemon=True,
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
            logger.exception("ControlServer dispatch error: %s", e)
            return self._error(req_id, _ERR_INTERNAL, str(e))
        if req_id is None:
            return None  # JSON-RPC notification → no response
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        lc = self.launcher
        if method == "reload":
            lc.reload()
            return {"ok": True}
        if method == "status":
            return lc.status_dict()
        if method == "quit":
            # Defer shutdown so the response flushes before process exit.
            def _deferred():
                time.sleep(0.2)
                lc.shutdown()
            threading.Thread(target=_deferred, daemon=True).start()
            return {"ok": True}
        if method == "start":
            return {"ok": bool(lc.start())}
        if method == "stop":
            lc.stop()
            return {"ok": True}
        raise _MethodNotFound(method)

    @staticmethod
    def _error(req_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}


def _load_port() -> int:
    cfg_path = PROJECT_DIR / "config.yaml"
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            return cfg.get("server", {}).get("port", 5001)
        except Exception as e:
            logger.warning("Failed to read config.yaml: %s", e)
    return 5001


def _find_python() -> str:
    if os.name == "nt":
        venv_py = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = PROJECT_DIR / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _is_interactive() -> bool:
    if not sys.stdin.isatty():
        return False
    if os.name == "nt":
        return msvcrt is not None
    return True  # POSIX with tty


def _listeners(port: int) -> List[int]:
    """Return PIDs currently listening on the given port."""
    pids: set[int] = set()
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            for line in out.splitlines():
                if "LISTENING" in line and f":{port}" in line:
                    parts = line.strip().split()
                    if parts and parts[-1].isdigit():
                        pids.add(int(parts[-1]))
        else:
            # macOS / Linux: use lsof
            out = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(int(line))
    except Exception:
        pass
    return sorted(pids)


def _can_bind(port: int) -> bool:
    """Check whether the OS lets us bind to the port right now."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _ensure_port_free(port: int, timeout: float = 15) -> bool:
    """Kill listeners and wait until the port can be bound."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pids = _listeners(port)
        if not pids and _can_bind(port):
            return True
        for pid in pids:
            logger.info("Killing PID %d to free port %d", pid, port)
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=5,
                )
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        time.sleep(0.5)
    return not _listeners(port) and _can_bind(port)


class Launcher:
    def __init__(self):
        self.port = _load_port()
        self.python = _find_python()
        self.service = ManagedService(
            name="infoServer",
            command=self.python,
            args=[str(PROJECT_DIR / "main.py")],
            cwd=str(PROJECT_DIR),
            port=self.port,
            managed=True,
            auto_restart=False,
        )
        self._running = True
        self._reloading = False
        self._lock = threading.Lock()
        self._ctl_server: Optional[ControlServer] = None

    def start(self) -> bool:
        logger.info("Starting infoServer (port %d)...", self.port)
        if not _ensure_port_free(self.port, timeout=15):
            logger.error("Port %d still in use; cannot start infoServer", self.port)
            return False
        self.service.start()
        if not self.service.running:
            logger.error("Failed to start infoServer")
            return False
        logger.info("InfoServer running. PID=%s", self.service.pid)
        logger.info("Press 'r' to reload, 'q' to quit, 's' for status, 'h' for help.")
        return True

    def stop(self, timeout: float = 20):
        logger.info("Stopping infoServer (PID=%s)...", self.service.pid)
        self.service.stop(timeout=timeout)
        if not _ensure_port_free(self.port, timeout=15):
            logger.warning("Port %d still in use after stop", self.port)

    def reload(self):
        with self._lock:
            if not self._running or self._reloading:
                return
            self._reloading = True
        try:
            logger.info("Reloading infoServer...")
            self.stop()
            if not self._running:
                return
            self.start()
        finally:
            self._reloading = False

    def status_dict(self) -> dict:
        svc = self.service
        return {
            "running": bool(svc.running),
            "status": svc.status,
            "pid": svc.pid,
            "uptime": round(svc.uptime, 1) if svc.uptime else None,
            "port": self.port,
            "last_error": svc._last_error,
        }

    def status(self):
        d = self.status_dict()
        logger.info(
            "Status: %s | PID: %s | uptime: %s",
            d["status"], d["pid"], d["uptime"],
        )

    @staticmethod
    def help():
        print(
            """
Hotkeys:
  r / R   Reload infoServer (stop fully then start)
  q / Q   Stop service and quit launcher
  s / S   Show current status
  h / H   Show this help
"""
        )

    def shutdown(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._reloading = False
            self.stop()

    @staticmethod
    def _getch_posix() -> str:
        """Read a single character from stdin on POSIX (macOS/Linux)."""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            # 用 setcbreak 而非 setraw: setraw 关闭 OPOST 致 \n 不转 \r\n,
            # 阻塞等按键期间 relay 日志呈阶梯状(看着没换行)。setcbreak 保留 OPOST + ISIG(Ctrl+C)。
            tty.setcbreak(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

    def _input_loop(self):
        while self._running:
            if self._reloading:
                time.sleep(0.2)
                continue
            try:
                if os.name == "nt" and msvcrt is not None:
                    ch = msvcrt.getch().decode("utf-8", errors="ignore").lower()
                else:
                    ch = self._getch_posix().lower()
            except Exception:
                time.sleep(0.2)
                continue

            if ch == "r":
                threading.Thread(target=self.reload, daemon=True).start()
            elif ch == "q":
                threading.Thread(target=self.shutdown, daemon=True).start()
                break
            elif ch == "s":
                self.status()
            elif ch == "h":
                self.help()

    def run(self):
        no_input = "--no-input" in sys.argv

        # 单实例锁: 先绑定 launcher 控制管道再启动 host。管道已被占 =
        # 已有 launcher 在跑, ControlServer.start() 内部 raise SystemExit(1),
        # 不会启动第二套 host/子服务 (2026-08-19 双实例事故根因修复)。
        self._ctl_server = ControlServer(self)
        self._ctl_server.start()

        if not self.start():
            sys.exit(1)

        if _is_interactive() and not no_input:
            t = threading.Thread(target=self._input_loop, daemon=True)
            t.start()

        try:
            while self._running and (self.service.running or self._reloading):
                time.sleep(0.2)
        except KeyboardInterrupt:
            logger.info("Ctrl+C received")
        finally:
            if self._ctl_server is not None:
                self._ctl_server.stop()
            self.shutdown()
            logger.info("Launcher exited")


def main():
    Launcher().run()


if __name__ == "__main__":
    main()
