import logging
import math
import shutil
import uuid
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, Body
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from file_handler import UPLOAD_CHUNK_SIZE, TARGET_PARALLEL_CHUNKS, _guess_mime
from state import state

logger = logging.getLogger(__name__)


# Quick speed-test payload cap. Keeps the measurement "one-shot" and light,
# so it can never be mistaken for a bandwidth attack.
MAX_SPEEDTEST_BYTES = 8 * 1024 * 1024


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
    return HTMLResponse(
        idx.read_bytes(),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


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

    rel_path, _, display_name = await run_in_threadpool(state.fh.create_zip, files_data, zip_name)
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

    batch_path, display_name, total_size, file_names = await run_in_threadpool(
        state.fh.save_batch, files_data)
    msg = await state.chat.add_batch_message(
        ip, sender, batch_path, display_name, total_size, file_names,
    )
    logger.info("Batch upload: %d files (%d bytes) from %s", len(files), total_size, ip)
    return msg


# ── Chunked resumable upload ───────────────────────────────────────────────
#
# Flow: init (returns session + already-received bitmap for resume)
#   -> chunk xN (parallel raw-body POSTs, idempotent)
#   -> complete (verify + merge + create message) | DELETE (abort)
# Sessions are persisted in SQLite keyed by (fingerprint, device_ip), so a
# page refresh or WiFi drop resumes from the last received chunk.

@router.post("/api/upload/init")
async def upload_init(request: Request):
    _check_origin(request)
    assert state.db and state.fh
    ip = _get_client_ip(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    fingerprint = (data.get("fingerprint") or "").strip()
    filename = (data.get("filename") or "unnamed").strip() or "unnamed"
    try:
        file_size = int(data.get("file_size") or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid file_size")

    if not fingerprint:
        raise HTTPException(400, "fingerprint required")
    if file_size <= 0:
        raise HTTPException(400, "file_size must be positive")

    # Opportunistic GC: stale sessions (>24h) -> aborted, finished rows dropped
    for sid in state.db.purge_stale_upload_sessions():
        state.fh.cleanup_session_files(sid)

    # Resume: same device + same file fingerprint + still active
    sess = state.db.find_active_upload_session(fingerprint, ip)
    if sess and sess["file_size"] == file_size:
        return {
            "upload_id": sess["id"],
            "chunk_size": sess["chunk_size"],
            "total_chunks": sess["total_chunks"],
            "received": sess["received"],
            "resumed": True,
        }

    upload_id = uuid.uuid4().hex[:16]
    # Keep 32MB chunks for large files, but shrink chunk size for medium files
    # so the browser's 6 parallel streams actually have multiple chunks to send.
    chunk_size = UPLOAD_CHUNK_SIZE
    if file_size < UPLOAD_CHUNK_SIZE * TARGET_PARALLEL_CHUNKS:
        chunk_size = max(1, math.ceil(file_size / TARGET_PARALLEL_CHUNKS))
    total_chunks = math.ceil(file_size / chunk_size)
    state.db.create_upload_session(
        upload_id, fingerprint, ip, filename, file_size,
        chunk_size, total_chunks,
    )
    state.fh.tmp_dir(upload_id).mkdir(parents=True, exist_ok=True)
    return {
        "upload_id": upload_id,
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "received": [],
        "resumed": False,
    }


@router.post("/api/upload/chunk")
async def upload_chunk(request: Request, upload_id: str, index: int):
    _check_origin(request)
    assert state.db and state.fh
    sess = state.db.get_upload_session(upload_id)
    if not sess:
        raise HTTPException(404, "Unknown upload session")
    if sess["status"] != "active":
        raise HTTPException(409, f"Session is {sess['status']}")
    if not 0 <= index < sess["total_chunks"]:
        raise HTTPException(400, "Chunk index out of range")

    # Stream raw body straight to disk - no multipart, no full buffering
    written, crc = await state.fh.write_chunk(upload_id, index, request.stream())

    # End-to-end integrity: client-computed CRC32 of the chunk payload.
    # TCP's 16-bit checksum lets rare corruption through; this catches it.
    client_crc = request.headers.get("x-chunk-crc32", "").strip().lower()
    if client_crc and client_crc != crc:
        state.fh.chunk_path(upload_id, index).unlink(missing_ok=True)
        raise HTTPException(400, f"Chunk CRC mismatch: server={crc} client={client_crc}")

    expected = state.fh.chunk_expected_size(
        sess["file_size"], sess["chunk_size"], index, sess["total_chunks"])
    if written != expected:
        # Remove the bad chunk so a retry re-sends it cleanly
        state.fh.chunk_path(upload_id, index).unlink(missing_ok=True)
        raise HTTPException(400, f"Chunk size mismatch: got {written}, expected {expected}")

    state.db.mark_chunk_received(upload_id, index)
    return {"ok": True, "index": index, "size": written, "crc32": crc}


@router.post("/api/upload/complete")
async def upload_complete(request: Request):
    _check_origin(request)
    assert state.db and state.fh and state.chat
    ip = _get_client_ip(request)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    sender = (data.get("sender") or "")
    upload_ids = data.get("upload_ids") or []
    if not upload_ids:
        raise HTTPException(400, "upload_ids required")

    sessions = []
    for uid in upload_ids:
        sess = state.db.get_upload_session(uid)
        if not sess:
            raise HTTPException(404, f"Unknown upload session {uid}")
        if sess["device_ip"] != ip:
            raise HTTPException(403, "Session belongs to another device")
        if sess["status"] != "active":
            raise HTTPException(409, f"Session {uid} is {sess['status']}")
        missing = [i for i in range(sess["total_chunks"])
                   if i not in set(sess["received"])
                   and not state.fh.chunk_path(uid, i).exists()]
        if missing:
            raise HTTPException(400, f"Session {uid} missing chunks: {missing[:10]}")
        sessions.append(sess)

    if len(sessions) == 1:
        sess = sessions[0]
        rel = state.fh.new_files_relative(sess["filename"])
        await run_in_threadpool(
            state.fh.merge_chunks, sess["id"], sess["total_chunks"], rel,
            sess["file_size"], sess["chunk_size"])
        state.db.set_upload_session_status(sess["id"], "done")
        msg = await state.chat.add_file_message(
            ip, sender, rel, sess["filename"], sess["file_size"],
            _guess_mime(sess["filename"]),
        )
        return msg

    # Multiple files -> batch folder, one message (same UX as /api/messages/files)
    batch_rel = state.fh.new_batch_relative()
    total_size = 0
    names = []
    for sess in sessions:
        safe_name = state.fh.sanitize_name(sess["filename"] or "unnamed")
        await run_in_threadpool(
            state.fh.merge_chunks, sess["id"], sess["total_chunks"],
            f"{batch_rel}/{safe_name}", sess["file_size"], sess["chunk_size"])
        state.db.set_upload_session_status(sess["id"], "done")
        total_size += sess["file_size"]
        names.append(safe_name)

    display_name = f"{names[0]} 等 {len(names)} 个文件"
    msg = await state.chat.add_batch_message(
        ip, sender, batch_rel, display_name, total_size, names,
    )
    logger.info("Chunked batch upload: %d files (%d bytes) from %s",
                len(names), total_size, ip)
    return msg


@router.delete("/api/upload/{upload_id}")
async def upload_abort(upload_id: str, request: Request):
    _check_origin(request)
    assert state.db and state.fh
    ip = _get_client_ip(request)
    sess = state.db.get_upload_session(upload_id)
    if not sess:
        raise HTTPException(404, "Unknown upload session")
    if sess["device_ip"] != ip:
        raise HTTPException(403, "Session belongs to another device")
    state.fh.cleanup_session_files(upload_id)
    state.db.set_upload_session_status(upload_id, "aborted")
    return {"status": "ok", "upload_id": upload_id}


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


@router.get("/api/speedtest")
async def speedtest_download(bytes: int = 4 * 1024 * 1024):
    """One-shot download speed probe (capped, no-store)."""
    size = min(max(bytes, 1024), MAX_SPEEDTEST_BYTES)
    return Response(
        content=b"\0" * size,
        media_type="application/octet-stream",
        headers={"Content-Length": str(size), "Cache-Control": "no-store"},
    )


@router.post("/api/speedtest")
async def speedtest_upload(request: Request):
    """One-shot upload speed probe: read body and discard (capped)."""
    _check_origin(request)
    size = 0
    async for data in request.stream():
        size += len(data)
        if size > MAX_SPEEDTEST_BYTES:
            raise HTTPException(413, "Speedtest payload too large")
    return {"ok": True, "bytes": size}


CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


def _load_shared_theme_config() -> dict:
    """读根 config.yaml shared_theme 段 (单一真相源)。
    parlance 是主题 provider, 此处破 main.py '自包含无 config 依赖' 注释,
    以提供可配置的共享主题开关 (子服务前端经 /api/theme/config 查询)。"""
    try:
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        st = data.get("shared_theme") or {}
        return {
            "enabled": bool(st.get("enabled", True)),
            "exclude": list(st.get("exclude") or []),
        }
    except Exception:
        return {"enabled": True, "exclude": []}


@router.get("/api/theme/config")
async def get_theme_config():
    return _load_shared_theme_config()


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
