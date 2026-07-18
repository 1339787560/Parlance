#!/usr/bin/env python3
"""infoServer — pure ServiceGroup launcher (走法 A: 无 HTTP, 不占端口).

读 config.yaml → ServiceGroupManager.start_all → 阻塞等 SIGINT → stop_all。
host 不监听任何 TCP 端口; 所有子服务(含 parlanceChat) 由 config.yaml services 声明,
按 enabled 开关即装/卸 → 可拆卸性。
"""

import logging
import signal
import threading
import time
from pathlib import Path

import yaml

from service_manager import ServiceGroupManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def load_config() -> dict:
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        logger.warning("config.yaml not found, using defaults (no services)")
        return {"services": []}
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    config = load_config()

    svc_mgr = ServiceGroupManager(config.get("services") or [])
    svc_mgr.start_all()

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
        svc_mgr.stop_all()
        logger.info("Launcher shut down")


if __name__ == "__main__":
    main()
