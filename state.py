from typing import Optional
from pathlib import Path
from database import Database
from file_handler import FileHandler
from chat_manager import ChatManager
from service_manager import ServiceGroupManager


class AppState:
    """Shared application state, populated during lifespan."""

    def __init__(self):
        self.db: Optional[Database] = None
        self.fh: Optional[FileHandler] = None
        self.chat: Optional[ChatManager] = None
        self.static_dir: Optional[Path] = None
        self.svc_mgr: Optional[ServiceGroupManager] = None


state = AppState()
