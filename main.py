import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, Body
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from chat_manager import ChatManager
from database import Database
from file_handler import FileHandler
from friendship import FriendshipManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

# ── Globals (set during lifespan) ──────────────────────────────────────────
_config = {}
_db: Optional[Database] = None
_fh: Optional[FileHandler] = None
_chat: Optional[ChatManager] = None
_friendship_mgr: Optional[FriendshipManager] = None


def load_config() -> dict:
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        logger.warning("config.yaml not found, using defaults")
        return {
            "server": {"host": "0.0.0.0", "port": 8080, "upload_dir": "./uploads"},
            "database": {"path": "./data/chat.db"},
            "friendship_services": [],
        }
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _db, _fh, _chat, _friendship_mgr

    _config = load_config()
    svr = _config.get("server", {})
    db_cfg = _config.get("database", {})

    upload_dir = svr.get("upload_dir", "./uploads")
    db_path = db_cfg.get("path", "./data/chat.db")

    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _db = Database(db_path)
    _fh = FileHandler(upload_dir)
    _chat = ChatManager(_db, _config)

    # Launch friendship services
    _friendship_mgr = FriendshipManager(_config.get("friendship_services", []))
    _friendship_mgr.start_all()

    logger.info("Server started \u2014 http://%s:%d", svr.get("host", "0.0.0.0"), svr.get("port", 8080))
    yield

    # Shutdown
    if _chat:
        await _chat.sse.shutdown()
    if _friendship_mgr:
        _friendship_mgr.stop_all()
    if _db:
        _db.close()
    logger.info("Server shut down")


app = FastAPI(lifespan=lifespan, title="LAN InfoShare")

# ── Static files ───────────────────────────────────────────────────────────
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

style_dir = Path(__file__).parent / "style"
if style_dir.exists():
    app.mount("/style", StaticFiles(directory=str(style_dir)), name="style")


# ── Helpers ────────────────────────────────────────────────────────────────
def get_client_ip(request: Request) -> str:
    host = request.client.host if request.client else "0.0.0.0"
    return host


def _check_origin(request: Request):
    """Reject cross-origin state-changing requests (CSRF)."""
    origin = request.headers.get("origin")
    if origin:
        host = request.headers.get("host", "")
        allowed = [f"http://{host}", f"https://{host}"]
        if origin not in allowed:
            raise HTTPException(403, "Cross-origin requests not allowed")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


# ── Routes ─────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    idx = static_dir / "index.html"
    if not idx.exists():
        raise HTTPException(500, "index.html not found")
    return HTMLResponse(idx.read_bytes())


@app.get("/api/messages")
async def get_messages(limit: int = 100, before_id: Optional[int] = None,
                       sender_ip: Optional[str] = None):
    assert _chat
    return _chat.get_messages(limit=limit, before_id=before_id, sender_ip=sender_ip)


@app.post("/api/messages/text")
async def send_text(request: Request):
    assert _chat
    ip = get_client_ip(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    content = (data.get("content") or "").strip()
    sender = (data.get("sender") or "")
    if not content:
        raise HTTPException(400, "Content cannot be empty")
    msg = await _chat.add_text_message(ip, sender, content)
    return msg


@app.post("/api/messages/file")
async def upload_file(request: Request, file: UploadFile, sender: str = Form("")):
    _check_origin(request)
    assert _chat and _fh
    ip = get_client_ip(request)
    data = await file.read()
    rel_path, full_path = _fh.save_file(data, file.filename or "unnamed")
    msg = await _chat.add_file_message(
        ip, sender, rel_path,
        file.filename or "unnamed",
        len(data),
        file.content_type or "application/octet-stream",
    )
    return msg


@app.post("/api/messages/zip")
async def upload_zip(request: Request, sender: str = Form(""),
                     zip_name: str = Form("files"), files: list[UploadFile] = ...):
    """Upload multiple files \u2192 server creates ZIP."""
    _check_origin(request)
    assert _chat and _fh
    ip = get_client_ip(request)

    if not files:
        raise HTTPException(400, "No files provided")

    files_data = []
    for f in files:
        data = await f.read()
        files_data.append((data, f.filename or "unnamed"))

    rel_path, _, display_name = _fh.create_zip(files_data, zip_name)
    file_size = (Path(_fh.upload_dir) / rel_path).stat().st_size

    msg = await _chat.add_zip_message(
        ip, sender, rel_path, display_name, file_size, len(files_data),
    )
    return msg


@app.get("/api/download/{msg_id}")
async def download(msg_id: int, request: Request):
    assert _db and _fh
    msg = _db.get_message(msg_id)
    if not msg or not msg["file_path"]:
        raise HTTPException(404, "File not found")

    file_path = Path(_fh.upload_dir) / msg["file_path"]
    if not file_path.exists():
        raise HTTPException(404, "File not found on disk")

    file_size = file_path.stat().st_size
    return await _fh.stream_file(file_path, msg["file_name"], file_size, request)


@app.get("/api/events")
async def sse_events(request: Request):
    """Server-Sent Events endpoint for real-time chat updates."""
    assert _chat
    q = await _chat.sse.subscribe()
    return StreamingResponse(
        _chat.sse.event_generator(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/whoami")
async def whoami(request: Request):
    return {"ip": get_client_ip(request)}


@app.get("/api/theme")
async def get_theme(request: Request):
    assert _db
    ip = get_client_ip(request)
    return {"theme": _db.get_theme(ip)}


@app.post("/api/theme")
async def set_theme(request: Request, data: dict = Body(...)):
    assert _db
    ip = get_client_ip(request)
    theme = data.get("theme", "")
    _db.set_theme(ip, theme)
    return {"status": "ok", "theme": theme}


@app.get("/api/profile")
async def get_profile(request: Request):
    assert _db
    ip = get_client_ip(request)
    name = _db.get_profile(ip)
    return {"ip": ip, "display_name": name}


@app.post("/api/profile")
async def set_profile(request: Request, data: dict = Body(...)):
    assert _db
    ip = get_client_ip(request)
    display_name = data.get("display_name", "").strip()[:30]
    _db.set_profile(ip, display_name)
    # Broadcast profile update
    await _chat.sse.broadcast("profile_update", {"ip": ip, "display_name": display_name})
    return {"status": "ok", "display_name": display_name}


@app.get("/api/users")
async def get_users():
    """List active users (IPs that have sent messages)."""
    assert _db
    return _db.get_active_ips()


@app.delete("/api/messages/{msg_id}")
async def delete_message(msg_id: int, request: Request):
    assert _db
    ip = get_client_ip(request)
    msg = _db.get_message(msg_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg["device_ip"] != ip:
        raise HTTPException(403, "Can only recall your own messages")
    # Delete associated file if exists
    if msg["file_path"] and _fh:
        file_path = Path(_fh.upload_dir) / msg["file_path"]
        if file_path.exists():
            file_path.unlink()
    deleted = _db.delete_message(msg_id)
    await _chat.sse.broadcast("message_deleted", {"id": msg_id})
    return {"status": "ok", "deleted": deleted}


@app.delete("/api/messages")
async def clear_all_messages(request: Request):
    """Clear ALL messages and uploaded files. Requires confirm=true and active user."""
    assert _db and _fh
    confirm = request.query_params.get("confirm", "")
    if confirm != "true":
        raise HTTPException(400, "Must confirm with ?confirm=true")
    ip = get_client_ip(request)
    # Require requester to be an active user (has sent at least one message)
    own = _db.get_messages(limit=1, sender_ip=ip)
    if not own:
        raise HTTPException(403, "Must be an active user to clear all messages")
    files = _db.clear_all_messages()
    # Delete associated files from database records
    for rel_path in files:
        f = Path(_fh.upload_dir) / rel_path
        if f.exists():
            f.unlink()
    # Also clean up orphaned files in uploads
    for subdir in ['files', 'zips']:
        d = Path(_fh.upload_dir) / subdir
        if d.exists():
            for p in d.iterdir():
                if p.is_file():
                    p.unlink()
    await _chat.sse.broadcast("messages_cleared", {})
    return {"status": "ok", "files_deleted": len(files)}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ── Entry point ────────────────────────────────────────────────────────────
def main():
    # Load config here too \u2014 lifespan runs when uvicorn imports the module
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) if Path("config.yaml").exists() else {}
    svr = cfg.get("server", {})
    host = svr.get("host", "0.0.0.0")
    port = svr.get("port", 8080)

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