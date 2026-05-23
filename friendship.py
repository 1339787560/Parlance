import logging
import os
import signal
import subprocess
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)


class FriendshipService:
    """Managed subprocess for a friendship Python service."""

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None,
                 cwd: Optional[str] = None, env: Optional[dict] = None,
                 auto_restart: bool = False):
        self.name = name
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.env = env
        self.auto_restart = auto_restart
        self._process: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self):
        if self.running:
            logger.warning("Service %s already running", self.name)
            return

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
            logger.info("Started friendship service '%s' (PID %d)", self.name, self._process.pid)

            # Monitor thread — logs output, handles auto-restart
            t = threading.Thread(target=self._monitor, daemon=True)
            t.start()
        except FileNotFoundError:
            logger.error("Friendship service '%s': command '%s' not found", self.name, self.command)

    def stop(self, timeout: float = 15):
        self._stop_event.set()
        if not self._process:
            return

        logger.info("Stopping friendship service '%s' (PID %d)", self.name, self._process.pid)

        try:
            if os.name == "nt":
                self._process.terminate()
            else:
                os.kill(self._process.pid, signal.SIGTERM)

            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Service '%s' didn't stop in %ds, killing", self.name, timeout)
            self._process.kill()
            self._process.wait(timeout=5)
        except Exception as e:
            logger.error("Error stopping service '%s': %s", self.name, e)

    def _monitor(self):
        """Read stdout/stderr until process exits, then maybe restart."""
        assert self._process is not None
        # Read until process dies
        for line in self._process.stdout:
            logger.info("[%s] %s", self.name, line.decode(errors="replace").rstrip())
        for line in self._process.stderr:
            logger.warning("[%s] %s", self.name, line.decode(errors="replace").rstrip())

        self._process.wait()
        exit_code = self._process.returncode
        logger.info("Service '%s' exited with code %d", self.name, exit_code)

        # Auto-restart unless we were asked to stop
        if self.auto_restart and not self._stop_event.is_set():
            logger.info("Auto-restarting service '%s'", self.name)
            self.start()


class FriendshipManager:
    """Manages all configured friendship services."""

    def __init__(self, services_config: list):
        self.services: List[FriendshipService] = []
        for cfg in services_config:
            svc = FriendshipService(
                name=cfg.get("name", "unnamed"),
                command=cfg["command"],
                args=cfg.get("args", []),
                cwd=cfg.get("cwd"),
                env=cfg.get("env"),
                auto_restart=cfg.get("auto_restart", False),
            )
            self.services.append(svc)

    def start_all(self):
        for svc in self.services:
            svc.start()

    def stop_all(self, timeout: float = 15):
        for svc in self.services:
            svc.stop(timeout=timeout)
