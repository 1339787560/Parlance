import logging
import os
import signal
import subprocess

import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Windows Job Object (foreground/managed mode only) ─────────────────────
_WIN_JOB = None

def _ensure_job():
    global _WIN_JOB
    if os.name != "nt" or _WIN_JOB is not None:
        return False
    import ctypes
    k32 = ctypes.windll.kernel32

    class BL(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO(ctypes.Structure):
        _fields_ = [("R", ctypes.c_uint64), ("W", ctypes.c_uint64), ("O", ctypes.c_uint64),
                    ("RT", ctypes.c_uint64), ("WT", ctypes.c_uint64), ("OT", ctypes.c_uint64)]

    class EL(ctypes.Structure):
        _fields_ = [("Basic", BL), ("Io", IO),
                    ("_p1", ctypes.c_uint32 * 4), ("_p2", ctypes.c_uint32 * 4),
                    ("_p3", ctypes.c_uint32 * 4), ("_p4", ctypes.c_uint32 * 4)]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False

    info = EL()
    info.Basic.LimitFlags = 0x2000
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        k32.CloseHandle(job)
        return False

    _WIN_JOB = job
    return True


def _assign_job(proc) -> bool:
    if os.name != "nt" or _WIN_JOB is None:
        return False
    import ctypes
    k32 = ctypes.windll.kernel32
    h = getattr(proc, '_handle', None)
    if not h:
        h = k32.OpenProcess(0x1F0FFF, False, proc.pid)
        if not h:
            return False
        ok = k32.AssignProcessToJobObject(_WIN_JOB, h)
        k32.CloseHandle(h)
        return bool(ok)
    return bool(k32.AssignProcessToJobObject(_WIN_JOB, h))


class ManagedService:
    """Subprocess wrapper. Two modes:

    managed=True (foreground/CLI):
      - Pipes stdout/stderr → logger
      - Assigned to Job Object → killed on parent exit
      - stop()/restart() works
      - ⚠ Orphan risk if parent force-killed before Job Object cleanup

    managed=False (daemon):
      - No pipe, no tracking, fire-and-forget
      - Child survives parent exit
      - stop()/restart() not supported
    """

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None,
                 cwd: Optional[str] = None, env: Optional[dict] = None,
                 auto_restart: bool = False, health_check: Optional[dict] = None,
                 tags: Optional[List[str]] = None, enabled: bool = True,
                 managed: bool = True, port: Optional[int] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.env = env or {}
        self.auto_restart = auto_restart
        self.health_check = health_check
        self.tags = tags or []
        self.enabled = enabled
        self.managed = managed
        self.port = port

        self._process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._start_time: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._last_error: Optional[str] = None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    @property
    def status(self) -> str:
        if self._process is None:
            return "stopped"
        if self.running:
            return "running"
        return "exited"

    @property
    def uptime(self) -> Optional[float]:
        if self.running and self._start_time:
            return time.time() - self._start_time
        return None

    # ── Lifecycle ───────────────────────────────────────────────────────

    @staticmethod
    def _get_parent_pid(pid: int) -> Optional[int]:
        """Get parent PID via wmic."""
        try:
            out = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}", "get", "parentprocessid"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    return int(line)
        except:
            pass
        return None

    @staticmethod
    def _free_port(port: int) -> bool:
        """Kill all processes holding the port via netstat + taskkill /T."""
        if os.name != "nt":
            return False
        try:
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10
            ).stdout
            killed = False
            for line in out.splitlines():
                if "LISTENING" in line and f":{port}" in line:
                    pid_str = line.strip().split()[-1]
                    if not pid_str or pid_str == "0":
                        continue
                    pid = int(pid_str)
                    # Kill child process tree
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                    )
                    # Kill parent (reloader) too
                    parent = ManagedService._get_parent_pid(pid)
                    if parent and parent != 1:  # not SYSTEM
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(parent)],
                            capture_output=True, timeout=5,
                        )
                    logger.info("[svc] Killed PID %s (parent %s) to free port %d",
                               pid_str, parent or "?", port)
                    killed = True
            return killed
        except:
            pass
        return False

    def start(self):
        if self.running:
            logger.warning("Service %s already running", self.name)
            return

        if not self.enabled:
            logger.info("Service '%s' disabled, skipping", self.name)
            return

        self._stop_event.clear()
        self._last_error = None
        self._exit_code = None

        # Free configured port before start
        if self.port is not None:
            self._free_port(self.port)
            time.sleep(0.3)  # let OS release socket

        proc_env = os.environ.copy()
        if self.env:
            proc_env.update(self.env)

        for attempt in range(2):
            try:
                if self.managed:
                    _ensure_job()
                    cf = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                    if hasattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB'):
                        cf |= subprocess.CREATE_BREAKAWAY_FROM_JOB

                    self._process = subprocess.Popen(
                        [self.command] + self.args,
                        cwd=self.cwd, env=proc_env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=cf,
                    )
                    _assign_job(self._process)
                else:
                    self._process = subprocess.Popen(
                        [self.command] + self.args,
                        cwd=self.cwd, env=proc_env,
                    )

                self._start_time = time.time()

                # Check immediate crash (e.g. port conflict)
                if self._process.poll() is not None:
                    code = self._process.returncode
                    if attempt == 0 and self.port is not None:
                        logger.warning("[svc] '%s' exited (code %d), freeing port and retry...",
                                       self.name, code)
                        self._free_port(self.port)
                        time.sleep(0.5)  # let OS release socket + reloader die
                        self._process = None
                        continue
                    self._last_error = f"Exit code {code}"
                    logger.error("[svc] '%s' start failed: %s", self.name, self._last_error)
                    return

                mode = "foreground" if self.managed else "daemon"
                logger.info("[svc] '%s' started (PID %d, %s)", self.name, self._process.pid, mode)

                t = threading.Thread(target=self._monitor if self.managed else self._wait_daemon, daemon=True)
                t.start()
                return

            except FileNotFoundError:
                self._last_error = f"Command '{self.command}' not found"
                logger.error("[svc] '%s': %s", self.name, self._last_error)
                return

    def stop(self, timeout: float = 15):
        if not self.managed:
            logger.info("Service '%s' is daemon, stop not supported", self.name)
            return
        self._stop_event.set()
        if not self._process:
            return

        pid = self._process.pid
        logger.info("Stopping service '%s' (PID %d)", self.name, pid)

        try:
            self._kill_tree(pid)
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Service '%s' didn't stop in %ds", self.name, timeout)
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
        except Exception as e:
            self._last_error = str(e)
            logger.error("Error stopping service '%s': %s", self.name, e)

    def restart(self, timeout: float = 15):
        self.stop(timeout=timeout)
        self.start()

    # ── Info ────────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "pid": self.pid,
            "running": self.running,
            "uptime": round(self.uptime, 1) if self.uptime else None,
            "exit_code": self._exit_code,
            "last_error": self._last_error,
            "auto_restart": self.auto_restart,
            "enabled": self.enabled,
            "managed": self.managed,
            "port": self.port,
            "tags": self.tags,
            "command": f"{self.command} {' '.join(self.args)}",
            "health_check_url": self.health_check.get("url") if self.health_check else None,
        }

    # ── Internal ────────────────────────────────────────────────────────

    def _kill_tree(self, pid: int):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _monitor(self):
        """Foreground mode: read pipes, log output, detect exit."""
        assert self._process is not None
        for line in self._process.stdout:
            logger.info("[%s] %s", self.name, line.decode(errors="replace").rstrip())
        for line in self._process.stderr:
            logger.warning("[%s] %s", self.name, line.decode(errors="replace").rstrip())
        self._process.wait()
        self._exit_code = self._process.returncode
        self._start_time = None
        logger.info("[svc] '%s' exited with code %d", self.name, self._exit_code)
        if self._exit_code != 0:
            self._last_error = f"Exit code {self._exit_code}"
        if self.auto_restart and not self._stop_event.is_set():
            logger.info("[svc] Auto-restarting '%s'", self.name)
            self.start()

    def _wait_daemon(self):
        """Daemon mode: just wait for exit, no pipe reading."""
        assert self._process is not None
        self._process.wait()
        self._exit_code = self._process.returncode
        self._start_time = None
        logger.info("[svc] daemon '%s' exited with code %d", self.name, self._exit_code)
        if self._exit_code != 0:
            self._last_error = f"Exit code {self._exit_code}"
        if self.auto_restart and not self._stop_event.is_set():
            logger.info("[svc] Auto-restarting daemon '%s'", self.name)
            self.start()


class ServiceGroupManager:
    """Manage group of external services."""

    def __init__(self, services_config: Optional[list] = None):
        self.services: List[ManagedService] = []
        self._name_map: Dict[str, ManagedService] = {}

        for cfg in (services_config or []):
            svc = ManagedService(
                name=cfg.get("name", "unnamed"),
                command=cfg["command"],
                args=cfg.get("args", []),
                cwd=cfg.get("cwd"),
                env=cfg.get("env", {}),
                auto_restart=cfg.get("auto_restart", False),
                health_check=cfg.get("health_check"),
                tags=cfg.get("tags", []),
                enabled=cfg.get("enabled", True),
                managed=cfg.get("managed", True),
                port=cfg.get("port"),
            )
            self.services.append(svc)
            self._name_map[svc.name] = svc

    def get(self, name: str) -> Optional[ManagedService]:
        return self._name_map.get(name)

    def start_all(self):
        foreground = [s for s in self.services if s.managed and s.enabled]
        daemon = [s for s in self.services if not s.managed and s.enabled]

        if foreground:
            logger.warning("─" * 50)
            logger.warning("⚠ 前台服务 (foreground/managed=true): 父进程退出时连带终止子进程")
            logger.warning("  但如果父进程被强制杀死（如任务管理器结束进程），")
            logger.warning("  子进程可能变成孤儿进程继续运行。")
            for s in foreground:
                logger.warning("  • %s (PID after start)", s.name)
            logger.warning("─" * 50)

        if daemon:
            logger.info("守护服务 (daemon/managed=false): 独立运行，不受父进程影响")
            for s in daemon:
                logger.info("  • %s", s.name)

        for svc in self.services:
            svc.start()

    def stop_all(self, timeout: float = 15):
        for svc in self.services:
            svc.stop(timeout=timeout)

    def status_all(self) -> List[Dict[str, Any]]:
        return [svc.to_dict() for svc in self.services]
