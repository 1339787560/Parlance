import os
import uuid
import urllib.parse
import zipfile
import io
from pathlib import Path
from typing import List, Tuple, Optional

import aiofiles
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse


# 256KB chunk — sweet spot between syscall overhead and memory pressure
_CHUNK_SIZE = 262144


class FileHandler:
    def __init__(self, upload_dir: str):
        self.upload_dir = Path(upload_dir).resolve()
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        (self.upload_dir / "files").mkdir(exist_ok=True)
        (self.upload_dir / "zips").mkdir(exist_ok=True)

    def save_file(self, data: bytes, filename: str) -> Tuple[str, Path]:
        """Save single file. Returns (relative_path, absolute_path)."""
        file_id = uuid.uuid4().hex[:16]
        safe_name = f"{file_id}-{_sanitize(filename)}"
        # files/abc123-report.pdf
        relative = f"files/{safe_name}"
        full = self.upload_dir / relative
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        return relative, full

    def create_zip(self, files_data: List[Tuple[bytes, str]], zip_name: str) -> Tuple[str, Path, str]:
        """Bundle files into ZIP. Returns (relative_path, absolute_path, display_name)."""
        zip_id = uuid.uuid4().hex[:8]
        display = f"{zip_name or 'files'}.zip"
        filename = f"{zip_name or 'files'}-{zip_id}.zip"
        relative = f"zips/{filename}"
        full = self.upload_dir / relative
        full.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(full, 'w', zipfile.ZIP_DEFLATED) as zf:
            for data, orig_name in files_data:
                zf.writestr(_sanitize(orig_name), data)

        return relative, full, display

    async def stream_file(self, path: Path, filename: str, file_size: int, request: Request):
        """Stream file with HTTP Range support for resumable download."""
        range_header = request.headers.get("range")
        content_type = _guess_mime(filename)

        if range_header:
            try:
                raw = range_header.strip().split("=")[-1]
                parts = raw.split("-", 1)
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
            except (ValueError, IndexError):
                raise HTTPException(400, "Invalid Range header")

            if start >= file_size:
                raise HTTPException(416, "Range Not Satisfiable")
            end = min(end, file_size - 1)
            length = end - start + 1

            return StreamingResponse(
                _iter_file_range(path, start, length),
                status_code=206,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(length),
                    "Content-Type": content_type,
                    "Accept-Ranges": "bytes",
                    "Content-Disposition": _content_disposition(filename),
                    "Cache-Control": "no-cache",
                },
            )

        # Full file
        return StreamingResponse(
            _iter_file(path, file_size),
            status_code=200,
            headers={
                "Content-Length": str(file_size),
                "Content-Type": content_type,
                "Accept-Ranges": "bytes",
                "Content-Disposition": _content_disposition(filename),
                "Cache-Control": "no-cache",
            },
        )


def _sanitize(name: str) -> str:
    """Remove path separators from filename."""
    return name.replace("/", "_").replace("\\", "_").strip()


def _content_disposition(filename: str) -> str:
    """Build Content-Disposition with RFC 5987 fallback for non-ASCII names."""
    try:
        filename.encode("latin-1")
        return f'attachment; filename="{filename}"'
    except UnicodeEncodeError:
        ascii_name = filename.encode("ascii", errors="replace").decode("ascii")
        encoded = urllib.parse.quote(filename, safe="")
        return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


def _guess_mime(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    mime_map = {
        ".zip": "application/zip",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".pdf": "application/pdf",
        ".mp4": "video/mp4",
        ".txt": "text/plain",
        ".html": "text/html",
        ".json": "application/json",
    }
    return mime_map.get(ext, "application/octet-stream")


async def _iter_file(path: Path, total: int):
    """Yield entire file asynchronously in large chunks."""
    async with aiofiles.open(path, "rb") as f:
        remaining = total
        while remaining > 0:
            chunk = await f.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


async def _iter_file_range(path: Path, start: int, length: int):
    """Yield byte range asynchronously."""
    async with aiofiles.open(path, "rb") as f:
        await f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = await f.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
