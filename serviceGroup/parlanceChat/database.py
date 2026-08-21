import json
import sqlite3
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).resolve())
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    @property
    def conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_ip TEXT NOT NULL,
                sender_name TEXT DEFAULT '',
                message_type TEXT NOT NULL DEFAULT 'text',
                content TEXT DEFAULT '',
                file_path TEXT DEFAULT '',
                file_name TEXT DEFAULT '',
                file_size INTEGER DEFAULT 0,
                file_mime TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_messages_created_at
                ON messages(created_at);
            CREATE TABLE IF NOT EXISTS theme_settings (
                device_ip TEXT PRIMARY KEY,
                theme_name TEXT NOT NULL DEFAULT 'red'
            );
            CREATE TABLE IF NOT EXISTS user_profiles (
                device_ip TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS upload_sessions (
                id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                device_ip TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                chunk_size INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL,
                received TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_upload_sessions_fp
                ON upload_sessions(fingerprint, device_ip, status);
        """)
        conn.commit()
        conn.close()

    def add_message(self, **kwargs) -> int:
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO messages
                (device_ip, sender_name, message_type, content,
                 file_path, file_name, file_size, file_mime)
            VALUES
                (:device_ip, :sender_name, :message_type, :content,
                 :file_path, :file_name, :file_size, :file_mime)
        """, kwargs)
        self.conn.commit()
        return c.lastrowid

    def get_message(self, msg_id: int) -> Optional[dict]:
        c = self.conn.cursor()
        c.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
        row = c.fetchone()
        return dict(row) if row else None

    def get_messages(self, limit: int = 100, before_id: Optional[int] = None,
                     sender_ip: Optional[str] = None):
        c = self.conn.cursor()
        if sender_ip:
            if before_id:
                c.execute("""
                    SELECT * FROM messages
                    WHERE device_ip = ? AND id < ?
                    ORDER BY id DESC LIMIT ?
                """, (sender_ip, before_id, limit))
            else:
                c.execute("""
                    SELECT * FROM messages
                    WHERE device_ip = ?
                    ORDER BY id DESC LIMIT ?
                """, (sender_ip, limit))
        elif before_id:
            c.execute("""
                SELECT * FROM messages
                WHERE id < ?
                ORDER BY id DESC LIMIT ?
            """, (before_id, limit))
        else:
            c.execute("""
                SELECT * FROM messages
                ORDER BY id DESC LIMIT ?
            """, (limit,))
        rows = c.fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_theme(self, ip: str) -> str:
        c = self.conn.cursor()
        c.execute("SELECT theme_name FROM theme_settings WHERE device_ip = ?", (ip,))
        row = c.fetchone()
        return row["theme_name"] if row else "red"

    def set_theme(self, ip: str, theme: str):
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO theme_settings (device_ip, theme_name)
            VALUES (?, ?)
            ON CONFLICT(device_ip) DO UPDATE SET theme_name = excluded.theme_name
        """, (ip, theme))
        self.conn.commit()

    # ── User profiles ────────────────────────────────────────────────
    def get_profile(self, ip: str) -> str:
        c = self.conn.cursor()
        c.execute("SELECT display_name FROM user_profiles WHERE device_ip = ?", (ip,))
        row = c.fetchone()
        return row["display_name"] if row else ""

    def set_profile(self, ip: str, name: str):
        name = name.strip()[:30]
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO user_profiles (device_ip, display_name)
            VALUES (?, ?)
            ON CONFLICT(device_ip) DO UPDATE SET display_name = excluded.display_name
        """, (ip, name))
        self.conn.commit()

    def get_all_profiles(self) -> list[dict]:
        c = self.conn.cursor()
        c.execute("SELECT device_ip, display_name FROM user_profiles WHERE display_name != ''")
        return [dict(r) for r in c.fetchall()]

    def get_active_ips(self) -> list[dict]:
        """Return distinct IPs that have sent messages, with their display names."""
        c = self.conn.cursor()
        c.execute("""
            SELECT m.device_ip,
                   COALESCE(u.display_name, '') as display_name
            FROM messages m
            LEFT JOIN user_profiles u ON m.device_ip = u.device_ip
            GROUP BY m.device_ip
            ORDER BY MAX(m.id) DESC
        """)
        return [dict(r) for r in c.fetchall()]

    # ── Upload sessions (chunked/resumable upload) ──────────────────

    def create_upload_session(self, session_id: str, fingerprint: str, device_ip: str,
                              filename: str, file_size: int, chunk_size: int,
                              total_chunks: int):
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO upload_sessions
                (id, fingerprint, device_ip, filename, file_size,
                 chunk_size, total_chunks, received, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 'active')
        """, (session_id, fingerprint, device_ip, filename,
              file_size, chunk_size, total_chunks))
        self.conn.commit()

    def find_active_upload_session(self, fingerprint: str, device_ip: str) -> Optional[dict]:
        c = self.conn.cursor()
        c.execute("""
            SELECT * FROM upload_sessions
            WHERE fingerprint = ? AND device_ip = ? AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
        """, (fingerprint, device_ip))
        row = c.fetchone()
        if row:
            d = dict(row)
            d["received"] = json.loads(d["received"] or "[]")
            return d
        return None

    def get_upload_session(self, session_id: str) -> Optional[dict]:
        c = self.conn.cursor()
        c.execute("SELECT * FROM upload_sessions WHERE id = ?", (session_id,))
        row = c.fetchone()
        if row:
            d = dict(row)
            d["received"] = json.loads(d["received"] or "[]")
            return d
        return None

    def mark_chunk_received(self, session_id: str, index: int):
        sess = self.get_upload_session(session_id)
        if not sess:
            return
        received = set(sess["received"])
        if index in received:
            return
        received.add(index)
        c = self.conn.cursor()
        c.execute("""
            UPDATE upload_sessions
            SET received = ?, updated_at = datetime('now', 'localtime')
            WHERE id = ?
        """, (json.dumps(sorted(received)), session_id))
        self.conn.commit()

    def set_upload_session_status(self, session_id: str, status: str):
        c = self.conn.cursor()
        c.execute("""
            UPDATE upload_sessions
            SET status = ?, updated_at = datetime('now', 'localtime')
            WHERE id = ?
        """, (status, session_id))
        self.conn.commit()

    def purge_stale_upload_sessions(self, max_age_hours: int = 24) -> list[str]:
        """Mark stale active sessions aborted; return ids whose tmp dirs need cleanup."""
        c = self.conn.cursor()
        c.execute("""
            SELECT id FROM upload_sessions
            WHERE status = 'active'
              AND updated_at < datetime('now', 'localtime', ?)
        """, (f'-{max_age_hours} hours',))
        stale = [r["id"] for r in c.fetchall()]
        c.execute("""
            SELECT id FROM upload_sessions
            WHERE status IN ('done', 'aborted')
              AND updated_at < datetime('now', 'localtime', ?)
        """, (f'-{max_age_hours} hours',))
        cleanup = stale + [r["id"] for r in c.fetchall()]
        if stale:
            c.executemany(
                "UPDATE upload_sessions SET status = 'aborted' WHERE id = ?",
                [(i,) for i in stale])
            self.conn.commit()
        if cleanup:
            # remove finished rows; tmp dir cleanup is caller's job
            c.executemany(
                "DELETE FROM upload_sessions WHERE id = ? AND status != 'active'",
                [(i,) for i in cleanup])
            self.conn.commit()
        return cleanup

    # ── Message management ───────────────────────────────────────────
    def get_message(self, msg_id: int) -> Optional[dict]:
        c = self.conn.cursor()
        c.execute("SELECT * FROM messages WHERE id = ?", (msg_id,))
        row = c.fetchone()
        return dict(row) if row else None

    def delete_message(self, msg_id: int) -> Optional[dict]:
        msg = self.get_message(msg_id)
        if msg:
            c = self.conn.cursor()
            c.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
            self.conn.commit()
        return msg

    def clear_all_messages(self) -> list[dict]:
        c = self.conn.cursor()
        c.execute("SELECT file_path FROM messages WHERE file_path != ''")
        files = [r["file_path"] for r in c.fetchall()]
        c.execute("DELETE FROM messages")
        self.conn.commit()
        return files

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
