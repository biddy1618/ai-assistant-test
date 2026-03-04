"""
Unified data models for messages across all platforms.

Every connector (Gmail, Telegram, WhatsApp) maps its native message format
into these models before storing. This gives the AI agent a consistent
interface regardless of where the message came from.
"""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class Platform(str, enum.Enum):
    """Supported messaging platforms."""
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    GMAIL = "gmail"


class MessageType(str, enum.Enum):
    """Type of message content."""
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"          # Voice messages
    DOCUMENT = "document"    # PDFs, docs, etc.
    STICKER = "sticker"
    LOCATION = "location"
    CONTACT = "contact"
    EMAIL = "email"          # Full email (subject + body)
    UNKNOWN = "unknown"


class AttachmentMeta(BaseModel):
    """
    Metadata for a media attachment. We don't store the actual file —
    just enough info to describe it and fetch it on demand.
    """
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    duration_seconds: int | None = None   # For audio/video
    # Platform-specific ID needed to download the file later
    platform_file_id: str | None = None

    def summary(self) -> str:
        """Human-readable summary for the AI agent, e.g. '[audio, 0:43]'"""
        parts = [self.mime_type or "file"]
        if self.filename:
            parts = [self.filename]
        if self.duration_seconds is not None:
            mins, secs = divmod(self.duration_seconds, 60)
            parts.append(f"{mins}:{secs:02d}")
        if self.size_bytes and self.size_bytes > 0:
            if self.size_bytes > 1_000_000:
                parts.append(f"{self.size_bytes / 1_000_000:.1f} MB")
            else:
                parts.append(f"{self.size_bytes / 1_000:.0f} KB")
        return f"[{', '.join(parts)}]"


class Contact(BaseModel):
    """
    A person or group across any platform.
    The same real person may have multiple Contact entries (one per platform).
    """
    platform: Platform
    platform_id: str                       # Unique ID on that platform
    name: str                              # Display name
    phone: str | None = None               # For WhatsApp / Telegram
    email: str | None = None               # For Gmail
    is_group: bool = False
    group_members_count: int | None = None


class Message(BaseModel):
    """
    The core unified message model.
    Every message from every platform gets mapped to this.
    """
    # Identity
    id: str | None = None                  # DB-assigned ID (None before insert)
    platform: Platform
    platform_message_id: str               # Original ID on the platform
    
    # Conversation context
    chat_id: str                           # Which chat/thread/email-thread this belongs to
    chat_name: str | None = None           # Group name, contact name, or email subject
    
    # Sender
    sender_id: str
    sender_name: str
    is_outgoing: bool = False              # True if sent BY sister (not to her)
    
    # Content
    message_type: MessageType = MessageType.TEXT
    text: str | None = None                # Message body / email body
    subject: str | None = None             # Email subject (Gmail only)
    attachment: AttachmentMeta | None = None
    
    # Timestamps
    timestamp: datetime
    synced_at: datetime = Field(default_factory=datetime.utcnow)
    
    # For email threading
    reply_to_id: str | None = None         # Platform message ID this replies to
    thread_id: str | None = None           # Email thread ID (Gmail)

    def to_agent_text(self) -> str:
        """
        Render this message as a concise text line for the AI agent's context.
        Example: "[WhatsApp] Mom (2024-01-15 09:30): Hey, are you coming to dinner?
        """
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M")
        platform_tag = self.platform.value.capitalize()
        direction = "→" if self.is_outgoing else ""
        
        parts = [f"[{platform_tag}] {direction}{self.sender_name} ({ts})"]
        
        if self.subject:
            parts.append(f"Subject: {self.subject}")
        
        if self.text:
            # Truncate very long messages for context window efficiency
            text = self.text[:500] + "..." if len(self.text) > 500 else self.text
            parts.append(text)
        
        if self.attachment:
            parts.append(self.attachment.summary())
        
        return " | ".join(parts) if len(parts) > 1 else parts[0]


class SyncState(BaseModel):
    """
    Tracks sync progress per connector so we can resume incrementally.
    Each connector stores its own cursor/checkpoint here.
    """
    platform: Platform
    last_sync_at: datetime | None = None
    # Platform-specific cursor for incremental sync
    # Gmail: historyId, Telegram: message offset ID, WhatsApp: timestamp
    cursor: str | None = None
    # How many messages synced in total
    total_synced: int = 0
