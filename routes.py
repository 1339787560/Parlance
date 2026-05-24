import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, Body
from fastapi.responses import HTMLResponse, StreamingResponse

from state import state

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "0.0.0.0"


def _check_origin(request: Request):
    """Reject cross-origin state-changing requests (CSRF)."""
    origin = request.headers.get("origin")
    if origin:
        host = request.headers.get("host", "")
        allowed = [f"http://{host}", f"https://{host}"]
        if origin not in allowed:
            raise HTTPException(403, "Cross-origin requests not allowed")


# ── Router ─────────────────────────────────────────────────────────────────

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index():
    idx = state.static_dir / "index.html"
    if not idx.exists():
        raise HTTPException(500, "index.html not found")
    return HTMLResponse(idx.read_bytes())


@router.get("/api/messages")
async def get_messages(limit: int = 100, before_id: Optional[int] = None,
                       sender_ip: Optional[str] = None):
    assert state.chat
    return state.chat.get_messages(limit=limit, before_id=before_id, sender_ip=sender_ip)


@router.post("/api/messages/text")
async def send_text(request: Request):
    assert state.chat
    ip = _get_client_ip(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    content = (data.get("content") or "").strip()
    sender = (data.get("sender") or "")
    if not content:
        raise HTTPException(400, "Content cannot be empty")
    msg = await state.chat.add_text_message(ip, sender, content)
    return msg


@router.post("/api/messages/file")
async def upload_file(request: Request, file: UploadFile, sender: str = Form("")):
    _check_origin(request)
    assert state.chat and state.fh
    ip = _get_client_ip(request)
    data = await file.read()
    rel_path, _ = state.fh.save_file(data, file.filename or "unnamed")
    msg = await state.chat.add_file_message(
        ip, sender, rel_path,
        file.filename or "unnamed",
        len(data),
        file.content_type or "application/octet-stream",
    )
    return msg


@router.post("/api/messages/zip")
async def upload_zip(request: Request, sender: str = Form(""),
                     zip_name: str = Form("files"), files: list[UploadFile] = ...):
    """Upload multiple files -> server creates ZIP."""
    _check_origin(request)
    assert state.chat and state.fh
    ip = _get_client_ip(request)

    if not files:
        raise HTTPException(400, "No files provided")

    files_data = []
    for f in files:
        data = await f.read()
        files_data.append((data, f.filename or "unnamed"))

    rel_path, _, display_name = state.fh.create_zip(files_data, zip_name)
    file_size = (Path(state.fh.upload_dir) / rel_path).stat().st_size

    msg = await state.chat.add_zip_message(
        ip, sender, rel_path, display_name, file_size, len(files_data),
    )
    return msg


@router.post("/api/messages/files")
async def upload_files(request: Request, sender: str = Form(""),
                       files: list[UploadFile] = ...):
    """Upload multiple files as a batch. Saved in one folder, shown as one message."""
    _check_origin(request)
    assert state.chat and state.fh
    ip = _get_client_ip(request)

    if not files:
        raise HTTPException(400, "No files provided")

    files_data = []
    for f in files:
        data = await f.read()
        files_data.append((data, f.filename or "unnamed"))

    batch_path, display_name, total_size, file_names = state.fh.save_batch(files_data)
    msg = await state.chat.add_batch_message(
        ip, sender, batch_path, display_name, total_size, file_names,
    )
    logger.info("Batch upload: %d files (%d bytes) from %s", len(files), total_size, ip)
    return msg


@router.get("/api/download/{msg_id}")
async def download(msg_id: int, request: Request):
    assert state.db and state.fh
    msg = state.db.get_message(msg_id)
    if not msg or not msg["file_path"]:
        raise HTTPException(404, "File not found")

    file_path = Path(state.fh.upload_dir) / msg["file_path"]
    if not file_path.exists():
        raise HTTPException(404, "File not found on disk")

    file_size = file_path.stat().st_size
    return await state.fh.stream_file(file_path, msg["file_name"], file_size, request)


@router.get("/api/download-batch/{msg_id}")
async def download_batch(msg_id: int, request: Request):
    """Download a batch upload folder as a ZIP file."""
    assert state.db and state.fh
    msg = state.db.get_message(msg_id)
    if not msg or msg["message_type"] != "batch_files" or not msg["file_path"]:
        raise HTTPException(404, "Batch not found")

    batch_dir = Path(state.fh.upload_dir) / msg["file_path"]
    return await state.fh.stream_batch_as_zip(batch_dir, request)


@router.get("/api/events")
async def sse_events(request: Request):
    """Server-Sent Events endpoint for real-time chat updates."""
    assert state.chat
    q = await state.chat.sse.subscribe()
    return StreamingResponse(
        state.chat.sse.event_generator(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/whoami")
async def whoami(request: Request):
    return {"ip": _get_client_ip(request)}


@router.get("/api/theme")
async def get_theme(request: Request):
    assert state.db
    ip = _get_client_ip(request)
    return {"theme": state.db.get_theme(ip)}


@router.post("/api/theme")
async def set_theme(request: Request, data: dict = Body(...)):
    assert state.db
    ip = _get_client_ip(request)
    theme = data.get("theme", "")
    state.db.set_theme(ip, theme)
    return {"status": "ok", "theme": theme}


@router.get("/api/profile")
async def get_profile(request: Request):
    assert state.db
    ip = _get_client_ip(request)
    name = state.db.get_profile(ip)
    return {"ip": ip, "display_name": name}


@router.post("/api/profile")
async def set_profile(request: Request, data: dict = Body(...)):
    assert state.db
    ip = _get_client_ip(request)
    display_name = data.get("display_name", "").strip()[:30]
    state.db.set_profile(ip, display_name)
    await state.chat.sse.broadcast("profile_update", {"ip": ip, "display_name": display_name})
    return {"status": "ok", "display_name": display_name}


@router.get("/api/users")
async def get_users():
    """List active users (IPs that have sent messages)."""
    assert state.db
    return state.db.get_active_ips()


@router.delete("/api/messages/{msg_id}")
async def delete_message(msg_id: int, request: Request):
    assert state.db
    ip = _get_client_ip(request)
    msg = state.db.get_message(msg_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    if msg["device_ip"] != ip:
        raise HTTPException(403, "Can only recall your own messages")
    # Delete associated file if exists
    if msg["file_path"] and state.fh:
        file_path = Path(state.fh.upload_dir) / msg["file_path"]
        if file_path.exists():
            if file_path.is_dir():
                shutil.rmtree(file_path)
            else:
                file_path.unlink()
    deleted = state.db.delete_message(msg_id)
    await state.chat.sse.broadcast("message_deleted", {"id": msg_id})
    return {"status": "ok", "deleted": deleted}


@router.delete("/api/messages")
async def clear_all_messages(request: Request):
    """Clear ALL messages and uploaded files. Requires confirm=true and active user."""
    assert state.db and state.fh
    confirm = request.query_params.get("confirm", "")
    if confirm != "true":
        raise HTTPException(400, "Must confirm with ?confirm=true")
    ip = _get_client_ip(request)
    own = state.db.get_messages(limit=1, sender_ip=ip)
    if not own:
        raise HTTPException(403, "Must be an active user to clear all messages")
    files = state.db.clear_all_messages()
    for rel_path in files:
        f = Path(state.fh.upload_dir) / rel_path
        if f.exists():
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
    for subdir in ['files', 'zips', 'batch']:
        d = Path(state.fh.upload_dir) / subdir
        if d.exists():
            for p in d.iterdir():
                if p.is_file():
                    p.unlink()
    await state.chat.sse.broadcast("messages_cleared", {})
    return {"status": "ok", "files_deleted": len(files)}


@router.get("/api/services")
async def list_services():
    """List all managed services with status."""
    if not state.svc_mgr:
        return {"services": []}
    return {"services": state.svc_mgr.status_all()}


@router.post("/api/services/{name}/start")
async def start_service(name: str):
    if not state.svc_mgr:
        raise HTTPException(503, "Service manager not initialized")
    svc = state.svc_mgr.get(name)
    if not svc:
        raise HTTPException(404, f"Service '{name}' not found")
    svc.start()
    return {"status": "ok", "service": svc.to_dict()}


@router.post("/api/services/{name}/stop")
async def stop_service(name: str):
    if not state.svc_mgr:
        raise HTTPException(503, "Service manager not initialized")
    svc = state.svc_mgr.get(name)
    if not svc:
        raise HTTPException(404, f"Service '{name}' not found")
    svc.stop()
    return {"status": "ok", "service": svc.to_dict()}


@router.post("/api/services/{name}/restart")
async def restart_service(name: str):
    if not state.svc_mgr:
        raise HTTPException(503, "Service manager not initialized")
    svc = state.svc_mgr.get(name)
    if not svc:
        raise HTTPException(404, f"Service '{name}' not found")
    svc.restart()
    return {"status": "ok", "service": svc.to_dict()}


@router.get("/api/health")
async def health():
    return {"status": "ok"}
