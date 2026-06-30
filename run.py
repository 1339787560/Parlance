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
from pathlib import Path
from typing import List

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

PROJECT_DIR = Path(__file__).resolve().parent


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
    venv_py = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _is_interactive() -> bool:
    return os.name == "nt" and sys.stdin.isatty() and msvcrt is not None


def _listeners(port: int) -> List[int]:
    """Return PIDs currently listening on the given port."""
    pids: set[int] = set()
    if os.name != "nt":
        return []
    try:
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
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=5,
            )
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

    def status(self):
        logger.info(
            "Status: %s | PID: %s | uptime: %s",
            self.service.status,
            self.service.pid,
            round(self.service.uptime, 1) if self.service.uptime else None,
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

    def _input_loop(self):
        while self._running:
            if self._reloading:
                time.sleep(0.2)
                continue
            try:
                ch = msvcrt.getch().decode("utf-8", errors="ignore").lower()
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
            self.shutdown()
            logger.info("Launcher exited")


def main():
    Launcher().run()


if __name__ == "__main__":
    main()
