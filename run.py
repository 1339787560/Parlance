#!/usr/bin/env python3
"""Interactive foreground sgmController for infoServer.

Usage:
    python run.py            # Start infoServer and listen for hotkeys
    python run.py --no-input # Start without keyboard listener (service mode)
    python run.py --config config.full.yaml   # 指定服务配置 (堡垒机全量; 本机缺省 config.yaml)

Hotkeys:
    r / R   Reload infoServer (stop fully then start)
    q / Q   Stop service and quit sgmController
    s / S   Show current status
    h / H   Show this help

发布通道 (2026-09-22 起本层承接): :5099 = `/api/deploy/*` 产物包直推 —— 见
deploy_service.py。放在本层 (L2) 的理由: 上级 L1 (`start.py --supervise`) 能重拉它
⇒ 它能换掉下面全部 (含 L3 main.py) 而"零组件需要自我更新"。
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
from service_manager import ManagedService, ServiceGroupManager
from deploy_service import (
    DEFAULT_PORT as DEPLOY_DEFAULT_PORT,
    DeployOrchestrator,
    DeployServer,
    SvcClient,
)

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


# 主动退出保留码: quit RPC / q 键 / Ctrl+C 三处会打 _deliberate 标记, 最终以本码退出。
# 契约方 = start.py (--supervise 时见本码即「别再拉」, 其余码 = 崩溃 → 重拉)。
# 注意 **stop 不在此列**: 它只停 sgManager, sgmController 留守（见 _dispatch("stop")）。
EXIT_DELIBERATE = 42


def _ctl_address():
    """Return (address, family) for the control socket on this platform."""
    if os.name == "nt":
        return (CTL_PIPE_WIN, "AF_PIPE")
    return (CTL_SOCKET_POSIX, "AF_UNIX")


class _MethodNotFound(Exception):
    pass


class ControlServer:
    """JSON-RPC control server, coexisting with the SgmController keyboard loop."""

    def __init__(self, controller: "SgmController"):
        self.controller = controller
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
            # 单实例锁: 控制管道被占 = 已有 sgmController 在跑。直接退出, 让已有实例
            # 独占服务 (2026-08-19 双实例事故根因: 第二套实例静默降级继续跑,
            # 导致 cwd-mcp 状态视图失真 + 端口互相抢占)。
            logger.error(
                "Control pipe %s already in use (%s) — another infoServer sgmController "
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
        lc = self.controller
        if method == "reload":
            lc.reload()
            return {"ok": True}
        if method == "status":
            return lc.status_dict()
        if method == "quit":
            # 主动退出: start.py --supervise 不得重拉。
            # ★ 标记必须打在 **SgmController** 上 —— run() 读的是 lc._deliberate 决定
            #   退出码; 2026-09-22 实测 bug: 这里曾打成 ControlServer 自己的属性,
            #   run() 读到 False → 退出码 0 → 被 --supervise 当"崩溃"重拉 (quit 失效)。
            lc.mark_deliberate()
            # Defer shutdown so the response flushes before process exit.
            def _deferred():
                time.sleep(0.2)
                lc.shutdown()
            threading.Thread(target=_deferred, daemon=True).start()
            return {"ok": True}
        if method == "start":
            return {"ok": bool(lc.start())}
        if method == "stop":
            # stop 只停 sgManager, sgmController **留守**（控制面不断, 便于"停下来更新"后
            # 直接 start/restart）。故这里不算主动退出、不打 _deliberate。
            lc.stop()
            return {"ok": True}
        raise _MethodNotFound(method)

    @staticmethod
    def _error(req_id, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}


def _config_args() -> List[str]:
    """提取 --config (转发 main.py + 端口预清理读同一文件)。"""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            return ["--config", argv[i + 1]]
        if a.startswith("--config="):
            return ["--config", a.split("=", 1)[1]]
    env_cfg = os.environ.get("INFOSERVER_CONFIG")
    if env_cfg:
        return ["--config", env_cfg]
    return []


def _load_port() -> int:
    ca = _config_args()
    cfg_path = PROJECT_DIR / (ca[1] if ca else "config.yaml")
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            return cfg.get("server", {}).get("port", 5001)
        except Exception as e:
            logger.warning("Failed to read %s: %s", cfg_path.name, e)
    return 5001


def _load_reload_exempt_services() -> List[dict]:
    """取出 config.yaml 里标了 `reload_exempt: true` 的服务声明 (没有则空表)。

    这类服务由**启动器**托管而不是宿主, 因为只有启动器分得清"启动 / 停止 / 重载"三个动作:
    重载 = 杀宿主再拉起宿主, 宿主两次都是被 `taskkill /F /T` 硬杀, 挂在宿主进程树下的
    服务必然被连带 (接 Job Object 也一样死 —— 2026-09-24 实测 dsh 就是这么被误伤两次)。
    启动器的子进程与宿主是兄弟关系, 不在宿主 /T 的树里, 所以能活过重载。
    """
    ca = _config_args()
    cfg_path = PROJECT_DIR / (ca[1] if ca else "config.yaml")
    if not cfg_path.exists():
        return []
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("Failed to read %s: %s", cfg_path.name, e)
        return []
    return [s for s in (cfg.get("services") or []) if s.get("reload_exempt")]


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


class SgmController:
    def __init__(self):
        self.port = _load_port()
        self.python = _find_python()
        self.service = ManagedService(
            name="infoServer",
            command=self.python,
            args=[str(PROJECT_DIR / "main.py")] + _config_args(),
            cwd=str(PROJECT_DIR),
            port=self.port,
            managed=True,
            auto_restart=False,
        )
        self._running = True
        self._reloading = False
        self._lock = threading.Lock()
        self._ctl_server: Optional[ControlServer] = None

        # 外部托管服务 (config 里 reload_exempt: true) —— 由启动器托管:
        #   启动 → 拉起 (端口被占则先杀掉再拉起); 停止 → 杀死; 重载 → 完全不碰。
        # 为什么不在宿主那侧托管: 见 _load_reload_exempt_services 的说明。
        self.external = ServiceGroupManager(_load_reload_exempt_services())

        # 主动退出标记 (quit RPC / q 键 / Ctrl+C 置位) — run() 读它决定是否以
        # EXIT_DELIBERATE 退出; 见模块头契约与 ControlServer._dispatch("quit")。
        self._deliberate = False

        # 发布通道 (:5099) —— 编排在 L2, 原语 (stop/start/swap_exe) 仍经 L3 宿主管道。
        self._deploy_svc = SvcClient()
        self._deploy: Optional[DeployOrchestrator] = DeployOrchestrator(
            root=str(PROJECT_DIR),
            svc=self._deploy_svc,
            on_self_update=self._self_update_for_deploy,
            on_reseat_l3=self._reseat_l3,
        )
        self._deploy_server: Optional[DeployServer] = None

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
        # 外部托管服务: 启动时拉起 (start() 内部先 _free_port —— "已存在就杀掉再拉起")
        if self.external.services:
            logger.info("启动外部托管服务 (%d 个): 端口被占则先杀掉再拉起", len(self.external.services))
            self.external.start_all()
        logger.info("Press 'r' to reload, 'q' to quit, 's' for status, 'h' for help.")
        return True

    def stop(self, timeout: float = 20, with_external: bool = True):
        logger.info("Stopping infoServer (PID=%s)...", self.service.pid)
        self.service.stop(timeout=timeout)
        if not _ensure_port_free(self.port, timeout=15):
            logger.warning("Port %d still in use after stop", self.port)
        # 停止 = 连外部托管服务一起杀 (需求 2)。reload 走 with_external=False 绕开这一支。
        if with_external and self.external.services:
            logger.info("停止外部托管服务 (%d 个)", len(self.external.services))
            self.external.stop_all(timeout=timeout)

    def reload(self):
        with self._lock:
            if not self._running or self._reloading:
                return
            self._reloading = True
        try:
            logger.info("Reloading infoServer...")
            # 重载只换宿主: 外部托管服务**不杀不拉**(需求 4) —— 它们与宿主是兄弟, 且启动器
            # 自己没在重启, 所以它们连"被动重启"都不会发生。
            self.stop(with_external=False)
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

    # ── 主动退出标记 (quit RPC / q 键 / Ctrl+C 共用; 唯一读取方 = run()) ──
    def mark_deliberate(self):
        self._deliberate = True

    # ── 发布通道 (:5099) ─────────────────────────────────────────────────
    def _start_deploy_server(self) -> None:
        port = int(os.environ.get("INFOSERVER_DEPLOY_PORT", str(DEPLOY_DEFAULT_PORT)))
        try:
            self._deploy_server = DeployServer("0.0.0.0", port, orchestrator=self._deploy)
            self._deploy_server.start()
        except OSError as e:
            # 绑不上 (:5099 被占 / 权限不足) 不致命 —— 启动器本体继续跑, 人还能进来修;
            # 但发布面缺失必须显眼 (旧 legacy 仍占 5099 时正是这个症状)。
            self._deploy_server = None
            logger.error("发布面 :%d 绑定失败 —— deploy 通道不可用: %s", port, e)

    def _stop_deploy_server(self) -> None:
        if self._deploy_server is not None:
            self._deploy_server.stop()
            self._deploy_server = None

    def _reseat_l3(self) -> None:
        """包动了 L3 (main.py/service_manager.py) → 停起 sgManager 让新码生效。

        L3 持 Job Object ⇒ 它一退, 全部子服务连坐 —— 这是"改 L3 必须接受"的代价
        (2026-09-22 决策日志)。L2 自身不死, 故由它发起是正路。
        """
        logger.info("[deploy] reseat L3 (sgManager) ...")
        self.stop()
        self.start()

    def _self_update_for_deploy(self) -> None:
        """包动了 L2 自身 (run.py/start.py) → 发布器换代。

        Python 不锁自己的 .py 文件, 此刻文件已换好; 但本层无法"重启自己", 故:
        停 L3 (释放端口与 Job) → 以**非保留码**退出 → L1 `start.py --supervise` 重拉新码。
        未被监督时退出 = 整栈下线且无人拉回 ⇒ 只记日志, 留人工重启。
        """
        if os.environ.get("INFOSERVER_SUPERVISED") != "1":
            logger.warning("[deploy] 包已换掉 L2 自身文件, 但当前**未受监督** —— "
                           "请人工重启 (start_admin.bat) 使新码生效")
            return
        time.sleep(2)          # 让 deploy.log 的最终 record 能被客户端轮询读到
        logger.info("[deploy] L2 自身换代: 停 L3 → 以非保留码退出, 等 L1 重拉新码")
        try:
            self.stop()
        except Exception as e:
            logger.warning("[deploy] 换代前停 L3 失败 (继续退出): %s", e)
        os._exit(1)            # 1 != EXIT_DELIBERATE(42) ⇒ L1 重拉

    @staticmethod
    def help():
        print(
            """
Hotkeys:
  r / R   Reload infoServer (stop fully then start)
  q / Q   Stop service and quit sgmController
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
                self.mark_deliberate()   # 主动退出: 见 _dispatch("quit")
                threading.Thread(target=self.shutdown, daemon=True).start()
                break
            elif ch == "s":
                self.status()
            elif ch == "h":
                self.help()

    def run(self):
        no_input = "--no-input" in sys.argv
        # 主动停止标记（quit/stop RPC、q 键、Ctrl+C）。父层 start.py --supervise 靠它决定
        # 「别再拉」还是「崩溃了要拉回来」。见模块头 EXIT_DELIBERATE 契约。
        self._deliberate = False

        # 单实例锁: 先绑定 sgmController 控制管道再启动 sgManager。管道已被占 =
        # 已有 sgmController 在跑, ControlServer.start() 内部 raise SystemExit(1),
        # 不会启动第二套 sgManager/子服务 (2026-08-19 双实例事故根因修复)。
        self._ctl_server = ControlServer(self)
        self._ctl_server.start()

        # 发布通道 (:5099): 与 ctl 管道并列的第二个面 —— 绑不上只告警不致命。
        self._start_deploy_server()

        if not self.start():
            sys.exit(1)

        if _is_interactive() and not no_input:
            t = threading.Thread(target=self._input_loop, daemon=True)
            t.start()

        try:
            # sgmController 的生命周期**独立于** sgManager: stop 只停服务组, 本层留守
            # （控制面还在 → 可再 start/restart，restart 依赖这一点）。
            # 只有 quit / q / Ctrl+C 才让它退出。
            # 旧条件 `and (self.service.running or self._reloading)` 会让 stop 连本层一起退,
            # 与设计文档（infoserver_spec_v6/02_生命周期.md「stop 只停 sgManager, sgmController
            # 留」）及 cwd_infoserver_stop 的「进程保留」描述相悖 → 2026-09-22 按用户裁定修正。
            while self._running:
                time.sleep(0.2)
        except KeyboardInterrupt:
            logger.info("Ctrl+C received")
            self.mark_deliberate()        # 用户主动按停: 不重拉
        finally:
            if self._ctl_server is not None:
                self._ctl_server.stop()
            self._stop_deploy_server()
            self.shutdown()
            logger.info("SgmController exited")

        # 主动停止 → 以保留码退出，父层(start.py --supervise)据此不再重拉；
        # 其余退出（崩溃 / main.py 意外死亡）走自然返回/非保留码 → 父层会重拉。
        #
        # **仅在受监督时**才用保留码：未被监督时保持历史上的 exit 0，避免把非 0 退出码
        # 暴露给别的宿主（如 Windows SCM —— SCM 会把非 0 记为该服务失败；仓里有
        # install_service.bat，故必须保守）。start.py 在监督模式下注入该 env。
        if self._deliberate and os.environ.get("INFOSERVER_SUPERVISED") == "1":
            sys.exit(EXIT_DELIBERATE)


def main():
    SgmController().run()


if __name__ == "__main__":
    main()
