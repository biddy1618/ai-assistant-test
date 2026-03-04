"""
Gmail connector — reads emails via Gmail API and stores them in the message store.

Auth: OAuth2 with gmail.readonly scope. Token loaded from config/token.json.
Sync strategy:
  - First sync: fetch last N days of emails (configurable)
  - Incremental sync: use Gmail historyId to fetch only new messages since last sync

HTTP transport: uses google.auth.transport.requests (requests library) instead of
httplib2, so that https_proxy env var is correctly respected in containerized envs.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
import google_auth_httplib2
import requests as _requests
from loguru import logger

from src.connectors.base import BaseConnector
from src.store.database import MessageStore
from src.store.models import Message, MessageType, Platform, SyncState

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

DEFAULT_CREDENTIALS = Path("config/credentials.json")
DEFAULT_TOKEN = Path("config/token.json")

INITIAL_SYNC_DAYS = 30
PAGE_SIZE = 100

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailConnector(BaseConnector):
    """Reads Gmail inbox and stores emails in the unified message store."""

    def __init__(
        self,
        store: MessageStore,
        credentials_file: Path = DEFAULT_CREDENTIALS,
        token_file: Path = DEFAULT_TOKEN,
    ):
        super().__init__(store)
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._session: google.auth.transport.requests.AuthorizedSession | None = None
        self._profile: dict | None = None

    @property
    def platform(self) -> Platform:
        return Platform.GMAIL

    # -- Auth ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Load OAuth token, refresh if expired. Returns True on success."""
        if not self.token_file.exists():
            logger.error(f"Token file not found: {self.token_file}. Run auth_google.py first.")
            return False

        creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)

        # AuthorizedSession uses requests under the hood — respects https_proxy env var
        self._session = google.auth.transport.requests.AuthorizedSession(creds)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                logger.info("Refreshing expired Gmail token...")
                self._session.credentials.refresh(
                    google.auth.transport.requests.Request(session=self._session)
                )
                self.token_file.write_text(creds.to_json())
                logger.info("Token refreshed and saved.")
            else:
                logger.error("Token invalid and cannot be refreshed. Run auth_google.py again.")
                return False

        self._profile = self._get(f"{GMAIL_BASE}/profile")
        logger.info(f"Gmail authenticated as {self._profile['emailAddress']}")
        return True

    # -- Sync ------------------------------------------------------------------

    async def sync(self, full: bool = False) -> int:
        if not self._session:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        sync_state = await self.get_sync_state()

        if full or sync_state is None or sync_state.cursor is None:
            count = await self._full_sync()
        else:
            count = await self._incremental_sync(sync_state.cursor)

        return count

    async def _full_sync(self) -> int:
        logger.info(f"Gmail full sync: fetching last {INITIAL_SYNC_DAYS} days...")
        after = (datetime.now(timezone.utc) - timedelta(days=INITIAL_SYNC_DAYS)).strftime("%Y/%m/%d")
        message_ids = self._list_message_ids(query=f"after:{after}")
        messages = self._fetch_messages(message_ids)
        count = await self.store.insert_messages_batch(messages)
        logger.info(f"Gmail full sync complete: {count} emails stored.")
        await self._save_sync_state(count)
        return count

    async def _incremental_sync(self, history_id: str) -> int:
        logger.info(f"Gmail incremental sync from historyId={history_id}...")
        try:
            new_ids = self._list_history_message_ids(history_id)
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning("Gmail historyId expired, falling back to full sync.")
                return await self._full_sync()
            raise

        if not new_ids:
            logger.info("Gmail incremental sync: no new messages.")
            await self._save_sync_state(0)
            return 0

        messages = self._fetch_messages(new_ids)
        count = await self.store.insert_messages_batch(messages)
        logger.info(f"Gmail incremental sync: {count} new emails stored.")
        await self._save_sync_state(count)
        return count

    # -- Gmail REST calls ------------------------------------------------------

    def _get(self, url: str, params: dict | None = None) -> dict:
        resp = self._session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _list_message_ids(self, query: str = "") -> list[str]:
        ids = []
        params: dict = {"maxResults": PAGE_SIZE, "q": query}
        while True:
            data = self._get(f"{GMAIL_BASE}/messages", params=params)
            ids.extend(m["id"] for m in data.get("messages", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            params["pageToken"] = page_token
        return ids

    def _list_history_message_ids(self, start_history_id: str) -> list[str]:
        ids = []
        params: dict = {"startHistoryId": start_history_id, "historyTypes": "messageAdded"}
        while True:
            data = self._get(f"{GMAIL_BASE}/history", params=params)
            for record in data.get("history", []):
                for added in record.get("messagesAdded", []):
                    ids.append(added["message"]["id"])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            params["pageToken"] = page_token
        return ids

    def _fetch_messages(self, message_ids: list[str]) -> list[Message]:
        messages = []
        for msg_id in message_ids:
            try:
                raw = self._get(f"{GMAIL_BASE}/messages/{msg_id}", params={"format": "full"})
                msg = self._parse_message(raw)
                if msg:
                    messages.append(msg)
            except Exception as e:
                logger.warning(f"Failed to fetch Gmail message {msg_id}: {e}")
        return messages

    def _parse_message(self, raw: dict) -> Message | None:
        headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}

        subject = headers.get("subject", "(no subject)")
        from_header = headers.get("from", "")
        date_header = headers.get("date", "")
        thread_id = raw.get("threadId")
        msg_id = raw["id"]

        sender_name, sender_email = _parse_email_address(from_header)
        if not sender_email:
            return None

        owner_email = self._profile["emailAddress"] if self._profile else ""
        is_outgoing = sender_email.lower() == owner_email.lower()

        timestamp = _parse_date(date_header)
        if timestamp is None:
            internal_ms = int(raw.get("internalDate", 0))
            timestamp = datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc)

        body = _extract_body(raw.get("payload", {}))

        return Message(
            platform=Platform.GMAIL,
            platform_message_id=msg_id,
            chat_id=thread_id or msg_id,
            chat_name=subject,
            sender_id=sender_email,
            sender_name=sender_name or sender_email,
            is_outgoing=is_outgoing,
            message_type=MessageType.EMAIL,
            text=body,
            subject=subject,
            timestamp=timestamp,
            thread_id=thread_id,
        )

    async def _save_sync_state(self, newly_synced: int) -> None:
        profile = self._get(f"{GMAIL_BASE}/profile")
        current_history_id = profile.get("historyId", "")
        existing = await self.get_sync_state()
        total = (existing.total_synced if existing else 0) + newly_synced
        await self.save_sync_state(SyncState(
            platform=Platform.GMAIL,
            last_sync_at=datetime.now(timezone.utc),
            cursor=current_history_id,
            total_synced=total,
        ))

    async def download_attachment(self, platform_file_id: str, dest: Path) -> Path:
        raise NotImplementedError("Gmail attachment download not yet implemented.")

    async def disconnect(self) -> None:
        if self._session:
            self._session.close()
        self._session = None
        self._profile = None


# -- Parsing utilities --------------------------------------------------------

def _parse_email_address(raw: str) -> tuple[str, str]:
    match = re.match(r'"?([^"<]*)"?\s*<([^>]+)>', raw.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "", raw.strip()


def _parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str).astimezone(timezone.utc)
    except Exception:
        return None


def _extract_body(payload: dict) -> str | None:
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace").strip()
    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", " ", html).strip()
    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result
    return None
