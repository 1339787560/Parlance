import logging
import os
import signal
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ManagedService:
    """Managed subprocess for external services."""

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None,
                 cwd: Optional[str] = None, env: Optional[dict] = None,
                 auto_restart: bool = False, health_check: Optional[dict] = None,
                 tags: Optional[List[str]] = None, enabled: bool = True):
        self.name = name
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.env = env or {}
        self.auto_restart = auto_restart
        self.health_check = health_check
        self.tags = tags or []
        self.enabled = enabled

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

        proc_env = os.environ.copy()
        if self.env:
            proc_env.update(self.env)

        try:
            self._process = subprocess.Popen(
                [self.command] + self.args,
                cwd=self.cwd,
                env=proc_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            self._start_time = time.time()
            logger.info("Started service '%s' (PID %d)", self.name, self._process.pid)

            t = threading.Thread(target=self._monitor, daemon=True)
            t.start()
        except FileNotFoundError:
            self._last_error = f"Command '{self.command}' not found"
            logger.error("Service '%s': %s", self.name, self._last_error)

    def _kill_tree(self, pid: int):
        """Kill entire process tree (handles Flask reloader child processes)."""
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass  # already dead

    def stop(self, timeout: float = 15):
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
            "tags": self.tags,
            "command": f"{self.command} {' '.join(self.args)}",
            "health_check_url": self.health_check.get("url") if self.health_check else None,
        }

    # ── Internal ────────────────────────────────────────────────────────

    def _monitor(self):
        assert self._process is not None

        for line in self._process.stdout:
            logger.info("[%s] %s", self.name, line.decode(errors="replace").rstrip())
        for line in self._process.stderr:
            logger.warning("[%s] %s", self.name, line.decode(errors="replace").rstrip())

        self._process.wait()
        self._exit_code = self._process.returncode
        self._start_time = None
        logger.info("Service '%s' exited with code %d", self.name, self._exit_code)

        if self._exit_code != 0:
            self._last_error = f"Exit code {self._exit_code}"

        if self.auto_restart and not self._stop_event.is_set():
            logger.info("Auto-restarting service '%s'", self.name)
            self.start()


class ServiceGroupManager:
    """Manage group of external services (subprocesses)."""

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
            )
            self.services.append(svc)
            self._name_map[svc.name] = svc

    def get(self, name: str) -> Optional[ManagedService]:
        return self._name_map.get(name)

    def start_all(self):
        for svc in self.services:
            svc.start()

    def stop_all(self, timeout: float = 15):
        for svc in self.services:
            svc.stop(timeout=timeout)

    def status_all(self) -> List[Dict[str, Any]]:
        return [svc.to_dict() for svc in self.services]
