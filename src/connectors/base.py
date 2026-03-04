"""
Base connector interface.

Every platform connector (Gmail, Telegram, WhatsApp) implements this ABC.
This gives the agent a uniform way to trigger syncs and fetch on-demand data
without knowing platform specifics.
"""

from __future__ import annotations

import abc
from pathlib import Path

from src.store.database import MessageStore
from src.store.models import Platform, SyncState


class BaseConnector(abc.ABC):
    """Abstract base for all message source connectors."""

    def __init__(self, store: MessageStore):
        self.store = store

    @property
    @abc.abstractmethod
    def platform(self) -> Platform:
        """Which platform this connector handles."""
        ...

    @abc.abstractmethod
    async def authenticate(self) -> bool:
        """
        Run the auth flow (OAuth, QR code, phone code, etc.).
        Returns True if auth succeeded.
        Should be idempotent — if already authed, just verify the session.
        """
        ...

    @abc.abstractmethod
    async def sync(self, full: bool = False) -> int:
        """
        Sync messages from the platform into the message store.
        
        Args:
            full: If True, ignore the sync cursor and pull everything.
                  If False, do incremental sync from last checkpoint.
        
        Returns:
            Number of new messages synced.
        """
        ...

    @abc.abstractmethod
    async def download_attachment(self, platform_file_id: str, dest: Path) -> Path:
        """
        Download a media attachment on demand.
        
        Args:
            platform_file_id: The platform-specific file reference
                              (stored in AttachmentMeta.platform_file_id)
            dest: Directory to save the file in.
        
        Returns:
            Path to the downloaded file.
        """
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Clean up connections, sessions, etc."""
        ...

    # -- Shared helpers -------------------------------------------------------

    async def get_sync_state(self) -> SyncState | None:
        """Get the current sync checkpoint for this platform."""
        return await self.store.get_sync_state(self.platform)

    async def save_sync_state(self, state: SyncState) -> None:
        """Persist the sync checkpoint."""
        await self.store.update_sync_state(state)
