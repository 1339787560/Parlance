import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from chat_manager import ChatManager
from database import Database
from file_handler import FileHandler
from routes import router
from service_manager import ServiceGroupManager
from state import state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

_config: dict = {}


def load_config() -> dict:
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        logger.warning("config.yaml not found, using defaults")
        return {
            "server": {"host": "0.0.0.0", "port": 8080, "upload_dir": "./uploads"},
            "database": {"path": "./data/chat.db"},
            "services": [],
        }
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config

    _config = load_config()
    svr = _config.get("server", {})
    db_cfg = _config.get("database", {})

    upload_dir = svr.get("upload_dir", "./uploads")
    db_path = db_cfg.get("path", "./data/chat.db")

    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    state.db = Database(db_path)
    state.fh = FileHandler(upload_dir)
    state.chat = ChatManager(state.db, _config)

    # Launch managed services (Job Object auto-kills on parent exit)
    svc_mgr = ServiceGroupManager(_config.get("services") or [])
    state.svc_mgr = svc_mgr
    svc_mgr.start_all()

    logger.info("Server started — http://%s:%d", svr.get("host", "0.0.0.0"), svr.get("port", 8080))
    yield

    # Graceful shutdown (Ctrl+C path)
    if state.chat:
        await state.chat.sse.shutdown()
    if svc_mgr:
        svc_mgr.stop_all()
    if state.db:
        state.db.close()
    logger.info("Server shut down")


app = FastAPI(lifespan=lifespan, title="LAN InfoShare")

# ── Static files ────────────────────────────────────────────────────────────
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
state.static_dir = static_dir
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

style_dir = Path(__file__).parent / "style"
if style_dir.exists():
    app.mount("/style", StaticFiles(directory=str(style_dir)), name="style")

# ── Middleware ───────────────────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# ── Routes ──────────────────────────────────────────────────────────────────
app.include_router(router)

# ── Entry point ─────────────────────────────────────────────────────────────
def _daemon_launch(host: str, port: int):
    """Relaunch self with pythonw.exe (no console), then exit current process."""
    if os.name != "nt":
        logger.info("Daemon mode only supported on Windows, running in foreground")
        return False
    if not sys.executable.endswith("python.exe"):
        logger.info("Not running from python.exe, daemon mode unavailable")
        return False

    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pythonw):
        logger.warning("pythonw.exe not found at %s, running in foreground", pythonw)
        return False

    import subprocess as sp
    sp.Popen(
        [pythonw, "-m", "uvicorn", "main:app",
         "--host", str(host), "--port", str(port),
         "--log-level", "info"],
        cwd=os.getcwd(),
        creationflags=sp.DETACHED_PROCESS | sp.CREATE_NEW_PROCESS_GROUP,
    )
    logger.info("infoServer daemon started on %s:%d (PID %d)", host, port, os.getpid())
    return True


def main():
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) if Path("config.yaml").exists() else {}
    svr = cfg.get("server", {})
    host = svr.get("host", "0.0.0.0")
    port = svr.get("port", 8080)

    # Daemon mode: relaunch with pythonw.exe, exit
    daemon = cfg.get("daemon", False)
    if daemon and not getattr(sys, 'frozen', False):
        if _daemon_launch(host, port):
            return  # parent exits, daemon keeps running

    import uvicorn
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        limit_concurrency=64,
        limit_max_requests=None,
        timeout_graceful_shutdown=1,
    )


if __name__ == "__main__":
    main()
