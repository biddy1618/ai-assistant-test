"""
Tests for the message store — verifies DB creation, insert, search, and sync state.
Run with: poetry run pytest tests/ -v
"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from src.store.database import MessageStore
from src.store.models import (
    AttachmentMeta,
    Contact,
    Message,
    MessageType,
    Platform,
    SyncState,
)


@pytest.fixture
async def store(tmp_path: Path):
    """Create a fresh in-memory-like store for each test."""
    db_path = tmp_path / "test.db"
    s = MessageStore(db_path=db_path)
    await s.connect()
    yield s
    await s.close()


def make_message(**overrides) -> Message:
    """Helper to create a test message with sensible defaults."""
    defaults = dict(
        platform=Platform.TELEGRAM,
        platform_message_id="msg_001",
        chat_id="chat_123",
        chat_name="Mom",
        sender_id="user_456",
        sender_name="Mom",
        is_outgoing=False,
        message_type=MessageType.TEXT,
        text="Hey, are you coming to dinner tonight?",
        timestamp=datetime(2024, 6, 15, 18, 30),
    )
    defaults.update(overrides)
    return Message(**defaults)


# -- Basic CRUD ---------------------------------------------------------------

async def test_insert_and_retrieve(store: MessageStore):
    msg = make_message()
    row_id = await store.insert_message(msg)
    assert row_id > 0

    results = await store.get_recent_messages(hours=999999)
    assert len(results) == 1
    assert results[0].text == "Hey, are you coming to dinner tonight?"
    assert results[0].sender_name == "Mom"


async def test_duplicate_insert_ignored(store: MessageStore):
    msg = make_message()
    await store.insert_message(msg)
    await store.insert_message(msg)  # Same platform + platform_msg_id

    results = await store.get_recent_messages(hours=999999)
    assert len(results) == 1  # Only one copy


async def test_batch_insert(store: MessageStore):
    messages = [
        make_message(platform_message_id=f"msg_{i}", text=f"Message {i}")
        for i in range(50)
    ]
    count = await store.insert_messages_batch(messages)
    assert count == 50

    results = await store.get_recent_messages(hours=999999, limit=100)
    assert len(results) == 50


# -- Search -------------------------------------------------------------------

async def test_full_text_search(store: MessageStore):
    await store.insert_message(make_message(
        platform_message_id="msg_1",
        text="Let's meet at the Italian restaurant on Friday",
    ))
    await store.insert_message(make_message(
        platform_message_id="msg_2",
        text="Don't forget to buy groceries",
    ))
    await store.insert_message(make_message(
        platform_message_id="msg_3",
        text="The restaurant reservation is confirmed",
    ))

    results = await store.search("restaurant")
    assert len(results) == 2
    texts = {r.text for r in results}
    assert "Don't forget to buy groceries" not in texts


async def test_search_by_sender(store: MessageStore):
    await store.insert_message(make_message(
        platform_message_id="msg_1", sender_name="Mom", text="Hello"
    ))
    await store.insert_message(make_message(
        platform_message_id="msg_2", sender_name="Dad", text="Hello too"
    ))

    results = await store.get_messages_by_sender("Mom")
    assert len(results) == 1
    assert results[0].sender_name == "Mom"


# -- Platform filtering -------------------------------------------------------

async def test_filter_by_platform(store: MessageStore):
    await store.insert_message(make_message(
        platform=Platform.TELEGRAM, platform_message_id="tg_1", text="Telegram msg"
    ))
    await store.insert_message(make_message(
        platform=Platform.GMAIL, platform_message_id="gm_1", text="Email msg"
    ))

    tg_results = await store.get_recent_messages(platform=Platform.TELEGRAM, hours=999999)
    assert len(tg_results) == 1
    assert tg_results[0].platform == Platform.TELEGRAM


# -- Attachments --------------------------------------------------------------

async def test_attachment_roundtrip(store: MessageStore):
    msg = make_message(
        platform_message_id="msg_attach",
        message_type=MessageType.AUDIO,
        text=None,
        attachment=AttachmentMeta(
            filename="voice_note.ogg",
            mime_type="audio/ogg",
            size_bytes=45000,
            duration_seconds=43,
            platform_file_id="file_abc123",
        ),
    )
    await store.insert_message(msg)

    results = await store.get_recent_messages(hours=999999)
    assert len(results) == 1
    assert results[0].attachment is not None
    assert results[0].attachment.duration_seconds == 43
    assert results[0].attachment.platform_file_id == "file_abc123"


# -- Sync state ---------------------------------------------------------------

async def test_sync_state(store: MessageStore):
    state = SyncState(
        platform=Platform.GMAIL,
        last_sync_at=datetime(2024, 6, 15, 12, 0),
        cursor="history_id_12345",
        total_synced=150,
    )
    await store.update_sync_state(state)

    loaded = await store.get_sync_state(Platform.GMAIL)
    assert loaded is not None
    assert loaded.cursor == "history_id_12345"
    assert loaded.total_synced == 150


# -- Stats & chats ------------------------------------------------------------

async def test_get_chats(store: MessageStore):
    await store.insert_message(make_message(
        platform_message_id="msg_1", chat_id="chat_mom", chat_name="Mom"
    ))
    await store.insert_message(make_message(
        platform_message_id="msg_2", chat_id="chat_mom", chat_name="Mom"
    ))
    await store.insert_message(make_message(
        platform_message_id="msg_3", chat_id="chat_work", chat_name="Work Group"
    ))

    chats = await store.get_chats()
    assert len(chats) == 2
    names = {c["chat_name"] for c in chats}
    assert names == {"Mom", "Work Group"}
