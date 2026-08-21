import os
import shutil
import uuid
import urllib.parse
import zipfile
import zlib
import io
from pathlib import Path
from typing import AsyncIterator, List, Tuple, Optional

import aiofiles
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse


# 256KB chunk — sweet spot between syscall overhead and memory pressure
_CHUNK_SIZE = 262144

# Resumable upload chunk size (32MB) - parallel TCP streams over WiFi/LAN
UPLOAD_CHUNK_SIZE = 32 * 1024 * 1024


class FileHandler:
    def __init__(self, upload_dir: str, tmp_dir: str = ""):
        self.upload_dir = Path(upload_dir).resolve()
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        (self.upload_dir / "files").mkdir(exist_ok=True)
        (self.upload_dir / "zips").mkdir(exist_ok=True)
        (self.upload_dir / "batch").mkdir(exist_ok=True)
        # tmp_dir can point to a fast disk (SSD/RAM disk) for chunk staging.
        self.tmp_dir_base = Path(tmp_dir).resolve() if tmp_dir else self.upload_dir / "tmp"
        self.tmp_dir_base.mkdir(parents=True, exist_ok=True)

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

    def save_batch(self, files_data: List[Tuple[bytes, str]]) -> Tuple[str, str, int, list]:
        """Save files to a batch folder. Returns (relative_path, display_name, total_size, filenames)."""
        batch_id = uuid.uuid4().hex[:12]
        batch_dir = self.upload_dir / "batch" / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)

        total_size = 0
        names = []
        for data, orig_name in files_data:
            safe_name = _sanitize(orig_name if orig_name else "unnamed")
            (batch_dir / safe_name).write_bytes(data)
            total_size += len(data)
            names.append(safe_name)

        display_name = f"{names[0]} 等 {len(names)} 个文件"
        relative = f"batch/{batch_id}"
        return relative, display_name, total_size, names

    # ── Chunked resumable upload ─────────────────────────────────────────────

    def tmp_dir(self, upload_id: str) -> Path:
        return self.tmp_dir_base / upload_id

    def chunk_path(self, upload_id: str, index: int) -> Path:
        return self.tmp_dir(upload_id) / f"{index:06d}"

    async def write_chunk(self, upload_id: str, index: int,
                          stream: AsyncIterator[bytes]) -> Tuple[int, str]:
        """Stream a raw request body chunk to tmp/{upload_id}/{index}.
        Returns (bytes_written, crc32_hex) - CRC is the end-to-end integrity
        check (TCP checksums are too weak to catch rare corruption)."""
        d = self.tmp_dir(upload_id)
        d.mkdir(parents=True, exist_ok=True)
        dest = self.chunk_path(upload_id, index)
        size = 0
        crc = 0
        # write via temp name + rename so a partial (interrupted) chunk never
        # masquerades as a complete one on disk
        tmp = dest.with_suffix(".part")
        async with aiofiles.open(tmp, "wb") as f:
            async for data in stream:
                size += len(data)
                crc = zlib.crc32(data, crc)
                await f.write(data)
        if size == 0:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, "Empty chunk body")
        tmp.replace(dest)
        return size, f"{crc & 0xFFFFFFFF:08x}"

    def chunk_expected_size(self, file_size: int, chunk_size: int, index: int,
                            total_chunks: int) -> int:
        if index == total_chunks - 1:
            return file_size - chunk_size * (total_chunks - 1)
        return chunk_size

    def merge_chunks(self, upload_id: str, total_chunks: int,
                     dest_relative: str, file_size: int = 0,
                     chunk_size: int = 0) -> Path:
        """Concatenate chunk files into final destination (blocking - run in threadpool).
        If file_size/chunk_size given, each chunk's on-disk size is re-verified
        (catches disk-level tampering/truncation since the upload)."""
        dest = self.upload_dir / dest_relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as out:
            for i in range(total_chunks):
                cp = self.chunk_path(upload_id, i)
                if not cp.exists():
                    raise HTTPException(400, f"Missing chunk {i}")
                if file_size and chunk_size:
                    expected = self.chunk_expected_size(
                        file_size, chunk_size, i, total_chunks)
                    actual = cp.stat().st_size
                    if actual != expected:
                        raise HTTPException(
                            400, f"Chunk {i} size drift: {actual} != {expected}")
                with open(cp, "rb") as f:
                    shutil.copyfileobj(f, out, _CHUNK_SIZE)
        self.cleanup_session_files(upload_id)
        return dest

    def cleanup_session_files(self, upload_id: str):
        d = self.tmp_dir(upload_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    def sanitize_name(self, name: str) -> str:
        return _sanitize(name)

    def new_files_relative(self, filename: str) -> str:
        """Generate a fresh relative path under files/ for a merged upload."""
        file_id = uuid.uuid4().hex[:16]
        return f"files/{file_id}-{_sanitize(filename)}"

    def new_batch_relative(self) -> str:
        """Generate a fresh batch folder path."""
        return f"batch/{uuid.uuid4().hex[:12]}"

    async def stream_batch_as_zip(self, batch_path: Path, request: Request):
        """Dynamically pack a batch folder into ZIP and stream it."""
        if not batch_path.exists() or not batch_path.is_dir():
            raise HTTPException(404, "Batch folder not found")

        files = sorted(batch_path.iterdir())
        if not files:
            raise HTTPException(404, "Batch folder is empty")

        zip_filename = batch_path.name  # batch_id
        content_type = "application/zip"

        # Build the full zip in memory first for simplicity
        # (batch files are generally small enough)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                if f.is_file():
                    data = f.read_bytes()
                    zf.writestr(f.name, data)
        buf.seek(0)
        zip_size = buf.getbuffer().nbytes

        range_header = request.headers.get("range")
        if range_header:
            try:
                raw = range_header.strip().split("=")[-1]
                parts = raw.split("-", 1)
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if len(parts) > 1 and parts[1] else zip_size - 1
            except (ValueError, IndexError):
                raise HTTPException(400, "Invalid Range header")
            if start >= zip_size:
                raise HTTPException(416, "Range Not Satisfiable")
            end = min(end, zip_size - 1)
            length = end - start + 1
            buf.seek(start)
            return StreamingResponse(
                _iter_bytes(buf, length),
                status_code=206,
                headers={"Content-Range": f"bytes {start}-{end}/{zip_size}", "Content-Length": str(length),
                         "Content-Type": content_type, "Accept-Ranges": "bytes",
                         "Content-Disposition": _content_disposition(f"{zip_filename}.zip"),
                         "Cache-Control": "no-cache"},
            )

        buf.seek(0)
        return StreamingResponse(
            _iter_bytes(buf, zip_size),
            status_code=200,
            headers={
                "Content-Length": str(zip_size),
                "Content-Type": content_type,
                "Accept-Ranges": "bytes",
                "Content-Disposition": _content_disposition(f"{zip_filename}.zip"),
                "Cache-Control": "no-cache",
            },
        )

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


async def _iter_bytes(buf: io.BytesIO, total: int):
    """Yield bytes from a BytesIO buffer in chunks."""
    remaining = total
    while remaining > 0:
        chunk = buf.read(min(_CHUNK_SIZE, remaining))
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