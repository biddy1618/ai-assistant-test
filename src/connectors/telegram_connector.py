"""
Telegram connector — reads personal Telegram messages via Telethon user client.

Auth: Phone number + SMS code (or 2FA password). Session persisted in
config/telegram.session so subsequent runs skip the interactive flow.

Sync strategy:
  - Full sync: fetch messages from all dialogs going back `initial_sync_days`.
  - Incremental sync: for each dialog, fetch only messages with ID > last cursor.

This is a *user* client (not a bot) — it reads personal Telegram history on
behalf of the account owner.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from loguru import logger
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl import types

from src.connectors.base import BaseConnector
from src.store.database import MessageStore
from src.store.models import (
    AttachmentMeta,
    Message,
    MessageType,
    Platform,
    SyncState,
)

# Batch size for inserting messages into the store
_BATCH_SIZE = 200


class TelegramConnector(BaseConnector):
    """
    Reads personal Telegram messages using a Telethon user client.

    Authenticates once via phone + SMS code (or 2FA password); the session is
    saved to `session_file` so subsequent runs are fully headless.
    """

    def __init__(
        self,
        store: MessageStore,
        api_id: int,
        api_hash: str,
        phone: str,
        session_file: Path = Path("config/telegram.session"),
        initial_sync_days: int = 30,
    ) -> None:
        """
        Args:
            store: Shared message store.
            api_id: Telegram API ID from https://my.telegram.org.
            api_hash: Telegram API hash from https://my.telegram.org.
            phone: Account phone number in international format, e.g. "+1234567890".
            session_file: Path to persist the Telethon session (gitignored).
            initial_sync_days: How many days back to fetch on a full sync.
        """
        super().__init__(store)
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_file = session_file
        self.initial_sync_days = initial_sync_days

        # Strip the ".session" suffix — Telethon appends it automatically.
        session_name = str(session_file.with_suffix(""))
        self._client = TelegramClient(session_name, api_id, api_hash)

    # -- Platform identity ----------------------------------------------------

    @property
    def platform(self) -> Platform:
        """Returns Platform.TELEGRAM."""
        return Platform.TELEGRAM

    # -- Auth -----------------------------------------------------------------

    async def authenticate(self) -> bool:
        """
        Connect to Telegram and ensure the session is authorised.

        If the session file does not exist (or the session is not authorised),
        Telethon will prompt interactively for the SMS code (and optionally the
        2FA password).  After the first successful auth the session is saved and
        all subsequent calls are fully headless.

        Returns:
            True if authorised, False on any error.
        """
        try:
            await self._client.connect()
        except Exception as exc:
            logger.error(f"Telegram: failed to connect — {exc}")
            return False

        try:
            if not await self._client.is_user_authorized():
                logger.info("Telegram: session not authorised — starting interactive auth...")
                await self._client.start(phone=self.phone)

            me = await self._client.get_me()
            display = me.username or me.first_name or str(me.id)
            logger.info(f"Telegram: authenticated as @{display}")
            return True
        except Exception as exc:
            logger.error(f"Telegram: authentication failed — {exc}")
            return False

    # -- Sync -----------------------------------------------------------------

    async def sync(self, full: bool = False) -> int:
        """
        Sync Telegram messages into the store.

        Args:
            full: If True, ignore the cursor and pull the last `initial_sync_days`.
                  If False, pull only messages newer than the stored cursor.

        Returns:
            Total number of new messages inserted.
        """
        if not self._client.is_connected():
            raise RuntimeError("Not connected. Call authenticate() first.")

        sync_state = await self.get_sync_state()
        cursor_id: int | None = None

        if not full and sync_state and sync_state.cursor:
            try:
                cursor_id = int(sync_state.cursor)
            except ValueError:
                logger.warning("Telegram: invalid cursor value, falling back to full sync.")
                cursor_id = None

        if full or cursor_id is None:
            logger.info(
                f"Telegram: full sync — fetching last {self.initial_sync_days} days "
                "from all dialogs."
            )
        else:
            logger.info(f"Telegram: incremental sync — fetching messages with ID > {cursor_id}.")

        cutoff_date: datetime | None = None
        if full or cursor_id is None:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.initial_sync_days)

        total_new = 0
        highest_id: int = cursor_id or 0

        batch: list[Message] = []

        async for dialog in self._client.iter_dialogs():
            dialog_name = dialog.name or str(dialog.id)
            try:
                async for msg in self._iter_dialog_messages(dialog, cursor_id, cutoff_date):
                    mapped = _map_message(msg, dialog)
                    if mapped is None:
                        continue
                    batch.append(mapped)
                    if msg.id > highest_id:
                        highest_id = msg.id
                    if len(batch) >= _BATCH_SIZE:
                        inserted = await self.store.insert_messages_batch(batch)
                        total_new += inserted
                        batch.clear()
            except FloodWaitError as exc:
                logger.warning(
                    f"Telegram: FloodWaitError on dialog '{dialog_name}' — "
                    f"sleeping {exc.seconds}s before continuing."
                )
                await asyncio.sleep(exc.seconds)
            except Exception as exc:
                logger.warning(
                    f"Telegram: failed to sync dialog '{dialog_name}' — {exc}. Skipping."
                )

        if batch:
            inserted = await self.store.insert_messages_batch(batch)
            total_new += inserted

        # Persist new sync state
        existing = await self.get_sync_state()
        new_state = SyncState(
            platform=Platform.TELEGRAM,
            last_sync_at=datetime.now(timezone.utc),
            cursor=str(highest_id) if highest_id else (sync_state.cursor if sync_state else None),
            total_synced=(existing.total_synced if existing else 0) + total_new,
        )
        await self.save_sync_state(new_state)

        logger.info(f"Telegram: sync complete — {total_new} new messages stored.")
        return total_new

    async def _iter_dialog_messages(
        self,
        dialog: types.Dialog,
        cursor_id: int | None,
        cutoff_date: datetime | None,
    ) -> AsyncIterator[types.Message]:
        """
        Yield raw Telethon messages from a single dialog.

        Uses `min_id` for incremental sync and `offset_date` for full sync.
        Handles FloodWaitError by re-raising so the caller can sleep and skip.
        """
        try:
            if cursor_id is not None:
                async for msg in self._client.iter_messages(
                    dialog,
                    min_id=cursor_id,
                    limit=None,
                ):
                    yield msg
            else:
                async for msg in self._client.iter_messages(
                    dialog,
                    offset_date=cutoff_date,
                    limit=None,
                ):
                    yield msg
        except FloodWaitError:
            raise
        except Exception as exc:
            raise exc

    # -- Attachment download --------------------------------------------------

    async def download_attachment(self, platform_file_id: str, dest: Path) -> Path:
        """
        Download a media attachment for a previously synced message.

        The `platform_file_id` is the Telegram message ID (stored as a string
        in `AttachmentMeta.platform_file_id`).  We pass the integer message ID
        directly to `client.download_media` which resolves the media reference.

        Args:
            platform_file_id: String representation of the Telegram message ID.
            dest: Directory (or full file path) to save the downloaded media.

        Returns:
            Path to the downloaded file.

        Raises:
            ValueError: If `platform_file_id` is not a valid integer.
            RuntimeError: If the download fails.
        """
        try:
            msg_id = int(platform_file_id)
        except ValueError as exc:
            raise ValueError(
                f"Telegram: platform_file_id must be an integer message ID, "
                f"got {platform_file_id!r}"
            ) from exc

        logger.info(f"Telegram: downloading media for message ID {msg_id} to {dest} ...")
        try:
            downloaded_path = await self._client.download_media(msg_id, file=dest)
        except Exception as exc:
            raise RuntimeError(
                f"Telegram: failed to download media for message ID {msg_id} — {exc}"
            ) from exc

        if downloaded_path is None:
            raise RuntimeError(
                f"Telegram: no media found for message ID {msg_id} (message may have no media)."
            )

        result = Path(downloaded_path)
        logger.info(f"Telegram: media saved to {result}")
        return result

    # -- Lifecycle ------------------------------------------------------------

    async def disconnect(self) -> None:
        """Disconnect the Telethon client and release resources."""
        if self._client.is_connected():
            await self._client.disconnect()
            logger.info("Telegram: disconnected.")


# -- Message mapping helpers --------------------------------------------------


def _get_sender_info(msg: types.Message) -> tuple[str, str]:
    """
    Extract (sender_id, sender_name) from a Telethon message.

    Falls back to the peer ID if no sender entity is available.
    """
    sender = msg.sender
    if sender is None:
        # Outgoing messages in some contexts may have no .sender
        peer_id = getattr(msg.peer_id, "user_id", None) or getattr(msg.peer_id, "channel_id", None)
        return str(msg.sender_id or peer_id or "unknown"), "Unknown"

    if isinstance(sender, types.User):
        parts = [sender.first_name or "", sender.last_name or ""]
        name = " ".join(p for p in parts if p).strip() or sender.username or str(sender.id)
        return str(sender.id), name

    if isinstance(sender, (types.Channel, types.Chat)):
        return str(sender.id), getattr(sender, "title", str(sender.id))

    return str(msg.sender_id or "unknown"), "Unknown"


def _get_chat_info(dialog: types.Dialog) -> tuple[str, str]:
    """Return (chat_id, chat_name) for a dialog."""
    entity = dialog.entity
    chat_id = str(dialog.id)
    if isinstance(entity, types.User):
        parts = [entity.first_name or "", entity.last_name or ""]
        name = " ".join(p for p in parts if p).strip() or entity.username or chat_id
        return chat_id, name
    if isinstance(entity, (types.Channel, types.Chat)):
        return chat_id, getattr(entity, "title", chat_id)
    return chat_id, dialog.name or chat_id


def _classify_media(msg: types.Message) -> tuple[MessageType, AttachmentMeta | None]:
    """
    Determine the MessageType and build AttachmentMeta for a Telethon message.

    Returns (MessageType.TEXT, None) for text-only messages.
    """
    media = msg.media

    if media is None:
        return MessageType.TEXT, None

    if isinstance(media, types.MessageMediaPhoto):
        return MessageType.IMAGE, AttachmentMeta(
            mime_type="image/jpeg",
            platform_file_id=str(msg.id),
        )

    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        if not isinstance(doc, types.Document):
            return MessageType.DOCUMENT, AttachmentMeta(platform_file_id=str(msg.id))

        mime = doc.mime_type or ""
        filename: str | None = None
        duration: int | None = None
        is_sticker = False

        for attr in doc.attributes:
            if isinstance(attr, types.DocumentAttributeFilename):
                filename = attr.file_name
            elif isinstance(attr, (types.DocumentAttributeAudio, types.DocumentAttributeVideo)):
                duration = getattr(attr, "duration", None)
                if duration is not None:
                    duration = int(duration)
            elif isinstance(attr, types.DocumentAttributeSticker):
                is_sticker = True

        attachment = AttachmentMeta(
            filename=filename,
            mime_type=mime,
            size_bytes=doc.size if hasattr(doc, "size") else None,
            duration_seconds=duration,
            platform_file_id=str(msg.id),
        )

        if is_sticker:
            return MessageType.STICKER, attachment
        if mime.startswith("audio/") or mime == "application/ogg":
            return MessageType.AUDIO, attachment
        if mime.startswith("video/"):
            return MessageType.VIDEO, attachment
        return MessageType.DOCUMENT, attachment

    if isinstance(
        media,
        (types.MessageMediaGeo, types.MessageMediaVenue, types.MessageMediaGeoLive),
    ):
        return MessageType.LOCATION, None

    if isinstance(media, types.MessageMediaContact):
        # Treat as text — contact name will appear in msg.text or can be inferred
        return MessageType.TEXT, None

    if isinstance(media, types.MessageMediaUnsupported):
        return MessageType.UNKNOWN, AttachmentMeta(platform_file_id=str(msg.id))

    # Polls, web pages, etc. — fall back to text
    return MessageType.TEXT, None


def _map_message(msg: types.Message, dialog: types.Dialog) -> Message | None:
    """
    Convert a raw Telethon `Message` object into the unified `Message` model.

    Returns None if the object is not a proper message (e.g. a service event).
    """
    # Skip service messages (join/leave/pin etc.)
    if not isinstance(msg, types.Message):
        return None

    chat_id, chat_name = _get_chat_info(dialog)
    sender_id, sender_name = _get_sender_info(msg)
    msg_type, attachment = _classify_media(msg)

    # Normalise timestamp to UTC-aware datetime
    timestamp: datetime = msg.date
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    reply_to_id: str | None = None
    if msg.reply_to and hasattr(msg.reply_to, "reply_to_msg_id"):
        reply_to_id = str(msg.reply_to.reply_to_msg_id)

    return Message(
        platform=Platform.TELEGRAM,
        platform_message_id=str(msg.id),
        chat_id=chat_id,
        chat_name=chat_name,
        sender_id=sender_id,
        sender_name=sender_name,
        is_outgoing=bool(msg.out),
        message_type=msg_type,
        text=msg.text or None,
        attachment=attachment,
        timestamp=timestamp,
        reply_to_id=reply_to_id,
    )
