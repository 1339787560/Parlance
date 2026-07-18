from typing import Optional
from pathlib import Path
from database import Database
from file_handler import FileHandler
from chat_manager import ChatManager


class AppState:
    """Shared chat application state, populated during lifespan."""

    def __init__(self):
        self.db: Optional[Database] = None
        self.fh: Optional[FileHandler] = None
        self.chat: Optional[ChatManager] = None
        self.static_dir: Optional[Path] = None


state = AppState()
