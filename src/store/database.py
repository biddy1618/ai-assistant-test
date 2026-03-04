"""
SQLite database with FTS5 full-text search for the message store.

Design decisions:
- Async via aiosqlite (the bot and connectors are all async)
- FTS5 virtual table for fast text search across all messages
- Separate sync_state table to track incremental sync per platform
- WAL mode for better concurrent read/write performance
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite

from src.store.models import (
    AttachmentMeta,
    Contact,
    Message,
    MessageType,
    Platform,
    SyncState,
)

DEFAULT_DB_PATH = Path.home() / ".sister-agent" / "messages.db"

# -- Schema ------------------------------------------------------------------

SCHEMA_SQL = """
-- Core messages table
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT NOT NULL,           -- 'whatsapp', 'telegram', 'gmail'
    platform_msg_id TEXT NOT NULL,           -- Original message ID
    chat_id         TEXT NOT NULL,
    chat_name       TEXT,
    sender_id       TEXT NOT NULL,
    sender_name     TEXT NOT NULL,
    is_outgoing     INTEGER NOT NULL DEFAULT 0,
    message_type    TEXT NOT NULL DEFAULT 'text',
    text            TEXT,                    -- Message body
    subject         TEXT,                    -- Email subject (Gmail)
    attachment_json TEXT,                    -- JSON-serialized AttachmentMeta
    timestamp       TEXT NOT NULL,           -- ISO 8601
    synced_at       TEXT NOT NULL,
    reply_to_id     TEXT,
    thread_id       TEXT,
    
    UNIQUE(platform, platform_msg_id)       -- Prevent duplicate inserts
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_messages_platform ON messages(platform);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_name);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);

-- FTS5 full-text search index over message text and metadata
-- This powers the "search conversations" feature
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    sender_name,
    chat_name,
    subject,
    text,
    content='messages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers to keep FTS index in sync with messages table
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, sender_name, chat_name, subject, text)
    VALUES (new.id, new.sender_name, new.chat_name, new.subject, new.text);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, sender_name, chat_name, subject, text)
    VALUES ('delete', old.id, old.sender_name, old.chat_name, old.subject, old.text);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, sender_name, chat_name, subject, text)
    VALUES ('delete', old.id, old.sender_name, old.chat_name, old.subject, old.text);
    INSERT INTO messages_fts(rowid, sender_name, chat_name, subject, text)
    VALUES (new.id, new.sender_name, new.chat_name, new.subject, new.text);
END;

-- Contacts table
CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT NOT NULL,
    platform_id     TEXT NOT NULL,
    name            TEXT NOT NULL,
    phone           TEXT,
    email           TEXT,
    is_group        INTEGER NOT NULL DEFAULT 0,
    group_members   INTEGER,
    
    UNIQUE(platform, platform_id)
);

-- Sync state per platform (for incremental sync)
CREATE TABLE IF NOT EXISTS sync_state (
    platform        TEXT PRIMARY KEY,
    last_sync_at    TEXT,
    cursor          TEXT,                    -- Platform-specific bookmark
    total_synced    INTEGER NOT NULL DEFAULT 0
);
"""


class MessageStore:
    """Async interface to the SQLite message database."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open DB connection, create tables if needed."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        
        # Performance: WAL mode + reasonable cache
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA cache_size=-64000")  # 64MB cache
        await self._db.execute("PRAGMA synchronous=NORMAL")
        
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    # -- Message CRUD ---------------------------------------------------------

    async def insert_message(self, msg: Message) -> int:
        """
        Insert a message. Returns the DB row ID.
        Silently skips duplicates (same platform + platform_message_id).
        """
        attachment_json = None
        if msg.attachment:
            attachment_json = msg.attachment.model_dump_json()

        result = await self.db.execute(
            """
            INSERT OR IGNORE INTO messages (
                platform, platform_msg_id, chat_id, chat_name,
                sender_id, sender_name, is_outgoing, message_type,
                text, subject, attachment_json, timestamp, synced_at,
                reply_to_id, thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.platform.value,
                msg.platform_message_id,
                msg.chat_id,
                msg.chat_name,
                msg.sender_id,
                msg.sender_name,
                int(msg.is_outgoing),
                msg.message_type.value,
                msg.text,
                msg.subject,
                attachment_json,
                msg.timestamp.isoformat(),
                msg.synced_at.isoformat(),
                msg.reply_to_id,
                msg.thread_id,
            ),
        )
        await self.db.commit()
        return result.lastrowid

    async def insert_messages_batch(self, messages: list[Message]) -> int:
        """Insert multiple messages in a single transaction. Returns count inserted."""
        rows = []
        for msg in messages:
            attachment_json = msg.attachment.model_dump_json() if msg.attachment else None
            rows.append((
                msg.platform.value,
                msg.platform_message_id,
                msg.chat_id,
                msg.chat_name,
                msg.sender_id,
                msg.sender_name,
                int(msg.is_outgoing),
                msg.message_type.value,
                msg.text,
                msg.subject,
                attachment_json,
                msg.timestamp.isoformat(),
                msg.synced_at.isoformat(),
                msg.reply_to_id,
                msg.thread_id,
            ))

        await self.db.executemany(
            """
            INSERT OR IGNORE INTO messages (
                platform, platform_msg_id, chat_id, chat_name,
                sender_id, sender_name, is_outgoing, message_type,
                text, subject, attachment_json, timestamp, synced_at,
                reply_to_id, thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await self.db.commit()
        return len(rows)

    # -- Query methods --------------------------------------------------------

    async def search(self, query: str, limit: int = 50) -> list[Message]:
        """Full-text search across all messages."""
        cursor = await self.db.execute(
            """
            SELECT m.* FROM messages m
            JOIN messages_fts fts ON m.id = fts.rowid
            WHERE messages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def get_recent_messages(
        self,
        platform: Platform | None = None,
        chat_id: str | None = None,
        hours: int = 24,
        limit: int = 100,
    ) -> list[Message]:
        """Get recent messages, optionally filtered by platform or chat."""
        conditions = ["timestamp > datetime('now', ?)" ]
        params: list = [f"-{hours} hours"]

        if platform:
            conditions.append("platform = ?")
            params.append(platform.value)
        if chat_id:
            conditions.append("chat_id = ?")
            params.append(chat_id)

        params.append(limit)
        where = " AND ".join(conditions)

        cursor = await self.db.execute(
            f"""
            SELECT * FROM messages
            WHERE {where}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            params,
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def get_messages_by_sender(
        self, sender_name: str, limit: int = 50
    ) -> list[Message]:
        """Find messages from a specific person (fuzzy name match)."""
        cursor = await self.db.execute(
            """
            SELECT * FROM messages
            WHERE sender_name LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (f"%{sender_name}%", limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def get_chats(self, platform: Platform | None = None) -> list[dict]:
        """List all chats with their last message time and message count."""
        condition = "WHERE platform = ?" if platform else ""
        params = [platform.value] if platform else []

        cursor = await self.db.execute(
            f"""
            SELECT 
                chat_id,
                chat_name,
                platform,
                COUNT(*) as message_count,
                MAX(timestamp) as last_message_at
            FROM messages
            {condition}
            GROUP BY platform, chat_id
            ORDER BY last_message_at DESC
            """,
            params,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_stats(self) -> dict:
        """Get overview statistics."""
        cursor = await self.db.execute(
            """
            SELECT 
                platform,
                COUNT(*) as count,
                MIN(timestamp) as earliest,
                MAX(timestamp) as latest
            FROM messages
            GROUP BY platform
            """
        )
        rows = await cursor.fetchall()
        return {row["platform"]: dict(row) for row in rows}

    # -- Sync state -----------------------------------------------------------

    async def get_sync_state(self, platform: Platform) -> SyncState | None:
        cursor = await self.db.execute(
            "SELECT * FROM sync_state WHERE platform = ?",
            (platform.value,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return SyncState(
            platform=Platform(row["platform"]),
            last_sync_at=datetime.fromisoformat(row["last_sync_at"]) if row["last_sync_at"] else None,
            cursor=row["cursor"],
            total_synced=row["total_synced"],
        )

    async def update_sync_state(self, state: SyncState) -> None:
        await self.db.execute(
            """
            INSERT INTO sync_state (platform, last_sync_at, cursor, total_synced)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(platform) DO UPDATE SET
                last_sync_at = excluded.last_sync_at,
                cursor = excluded.cursor,
                total_synced = excluded.total_synced
            """,
            (
                state.platform.value,
                state.last_sync_at.isoformat() if state.last_sync_at else None,
                state.cursor,
                state.total_synced,
            ),
        )
        await self.db.commit()

    # -- Contacts -------------------------------------------------------------

    async def upsert_contact(self, contact: Contact) -> None:
        await self.db.execute(
            """
            INSERT INTO contacts (platform, platform_id, name, phone, email, is_group, group_members)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, platform_id) DO UPDATE SET
                name = excluded.name,
                phone = excluded.phone,
                email = excluded.email,
                is_group = excluded.is_group,
                group_members = excluded.group_members
            """,
            (
                contact.platform.value,
                contact.platform_id,
                contact.name,
                contact.phone,
                contact.email,
                int(contact.is_group),
                contact.group_members_count,
            ),
        )
        await self.db.commit()

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> Message:
        """Convert a DB row back to a Message model."""
        attachment = None
        if row["attachment_json"]:
            attachment = AttachmentMeta.model_validate_json(row["attachment_json"])

        return Message(
            id=str(row["id"]),
            platform=Platform(row["platform"]),
            platform_message_id=row["platform_msg_id"],
            chat_id=row["chat_id"],
            chat_name=row["chat_name"],
            sender_id=row["sender_id"],
            sender_name=row["sender_name"],
            is_outgoing=bool(row["is_outgoing"]),
            message_type=MessageType(row["message_type"]),
            text=row["text"],
            subject=row["subject"],
            attachment=attachment,
            timestamp=datetime.fromisoformat(row["timestamp"]),
            synced_at=datetime.fromisoformat(row["synced_at"]),
            reply_to_id=row["reply_to_id"],
            thread_id=row["thread_id"],
        )
