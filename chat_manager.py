import asyncio
import json
import logging
from typing import Optional

from database import Database

logger = logging.getLogger(__name__)


class SSEManager:
    """Manages Server-Sent Events subscribers."""

    def __init__(self):
        self._clients: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._clients.append(q)
        logger.debug("SSE client connected (%d total)", len(self._clients))
        return q

    async def unsubscribe(self, q: asyncio.Queue):
        async with self._lock:
            if q in self._clients:
                self._clients.remove(q)
        logger.debug("SSE client disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, event: str, data: dict):
        async with self._lock:
            for client in self._clients:
                await client.put({"event": event, "data": data})

    async def shutdown(self):
        """Signal shutdown to all subscribers."""
        self._shutdown_event.set()
        async with self._lock:
            clients = list(self._clients)
        for q in clients:
            await q.put(None)

    async def event_generator(self, q: asyncio.Queue):
        """Async generator yielding SSE-formatted messages."""
        try:
            while not self._shutdown_event.is_set():
                msg = await q.get()
                if msg is None:
                    break
                yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await self.unsubscribe(q)


class ChatManager:
    """Business logic for chat messages."""

    def __init__(self, db: Database, config: dict):
        self.db = db
        self.config = config
        self.sse = SSEManager()

    async def add_text_message(self, ip: str, sender: str, text: str) -> dict:
        msg_id = self.db.add_message(
            device_ip=ip,
            sender_name=sender,
            message_type="text",
            content=text.strip(),
            file_path="",
            file_name="",
            file_size=0,
            file_mime="",
        )
        msg = self.db.get_message(msg_id)
        await self.sse.broadcast("new_message", msg)
        return msg

    async def add_file_message(self, ip: str, sender: str, file_path: str,
                                file_name: str, file_size: int, file_mime: str) -> dict:
        msg_id = self.db.add_message(
            device_ip=ip,
            sender_name=sender,
            message_type="file",
            content="",
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_mime=file_mime,
        )
        msg = self.db.get_message(msg_id)
        await self.sse.broadcast("new_message", msg)
        return msg

    async def add_zip_message(self, ip: str, sender: str, file_path: str,
                               file_name: str, file_size: int, file_count: int) -> dict:
        msg_id = self.db.add_message(
            device_ip=ip,
            sender_name=sender,
            message_type="zip",
            content=f"{file_count} files",
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_mime="application/zip",
        )
        msg = self.db.get_message(msg_id)
        await self.sse.broadcast("new_message", msg)
        return msg

    def get_messages(self, limit: int = 100, before_id: Optional[int] = None,
                      sender_ip: Optional[str] = None):
        return self.db.get_messages(limit=limit, before_id=before_id, sender_ip=sender_ip)
