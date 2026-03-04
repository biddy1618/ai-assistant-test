"""
Tests for the Telegram connector helper functions.

These tests cover pure functions only — no live Telegram connection is needed.
All Telethon objects are mocked with unittest.mock.MagicMock.

Run with: poetry run pytest tests/test_telegram_connector.py -v
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from telethon.tl import types

from src.connectors.telegram_connector import (
    _classify_media,
    _get_chat_info,
    _get_sender_info,
    _map_message,
)
from src.store.models import MessageType, Platform

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_user(
    user_id: int = 12345,
    first_name: str = "Alice",
    last_name: str = "Smith",
    username: str = "alice",
) -> MagicMock:
    """Return a MagicMock shaped like a telethon types.User."""
    user = MagicMock(spec=types.User)
    user.id = user_id
    user.first_name = first_name
    user.last_name = last_name
    user.username = username
    return user


def make_channel(channel_id: int = 99, title: str = "Test Channel") -> MagicMock:
    """Return a MagicMock shaped like a telethon types.Channel."""
    channel = MagicMock(spec=types.Channel)
    channel.id = channel_id
    channel.title = title
    return channel


def make_chat(chat_id: int = 77, title: str = "Test Chat") -> MagicMock:
    """Return a MagicMock shaped like a telethon types.Chat."""
    chat = MagicMock(spec=types.Chat)
    chat.id = chat_id
    chat.title = title
    return chat


def make_message(
    msg_id: int = 42,
    sender: object = None,
    sender_id: int = 12345,
    text: str = "Hello",
    out: bool = False,
    media: object = None,
    date: datetime | None = None,
    reply_to: object = None,
) -> MagicMock:
    """Return a MagicMock shaped like a telethon types.Message."""
    msg = MagicMock(spec=types.Message)
    msg.id = msg_id
    msg.sender = sender
    msg.sender_id = sender_id
    msg.text = text
    msg.out = out
    msg.media = media
    msg.date = date or datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
    msg.reply_to = reply_to
    msg.peer_id = MagicMock()
    # Make sure peer_id does not accidentally have user_id/channel_id unless set
    msg.peer_id.user_id = None
    msg.peer_id.channel_id = None
    return msg


def make_dialog(
    dialog_id: int = 99,
    name: str = "Test Chat",
    entity: object = None,
) -> MagicMock:
    """Return a MagicMock shaped like a telethon types.Dialog."""
    dialog = MagicMock(spec=types.Dialog)
    dialog.id = dialog_id
    dialog.name = name
    dialog.entity = entity
    return dialog


# ---------------------------------------------------------------------------
# _get_sender_info
# ---------------------------------------------------------------------------


class TestGetSenderInfo:
    """Tests for _get_sender_info()."""

    def test_user_sender_full_name(self) -> None:
        """User with first_name and last_name returns concatenated full name."""
        sender = make_user(user_id=1, first_name="Alice", last_name="Smith")
        msg = make_message(sender=sender, sender_id=1)

        sid, name = _get_sender_info(msg)

        assert sid == "1"
        assert name == "Alice Smith"

    def test_user_sender_first_name_only(self) -> None:
        """User with only first_name returns first name."""
        sender = make_user(user_id=2, first_name="Bob", last_name="", username="bob")
        msg = make_message(sender=sender, sender_id=2)

        sid, name = _get_sender_info(msg)

        assert sid == "2"
        assert name == "Bob"

    def test_user_sender_no_name_falls_back_to_username(self) -> None:
        """User with no first/last name falls back to username."""
        sender = make_user(user_id=3, first_name="", last_name="", username="ghostuser")
        msg = make_message(sender=sender, sender_id=3)

        sid, name = _get_sender_info(msg)

        assert sid == "3"
        assert name == "ghostuser"

    def test_user_sender_no_name_no_username_falls_back_to_id(self) -> None:
        """User with no name and no username falls back to str(sender.id)."""
        sender = make_user(user_id=4, first_name="", last_name="", username="")
        msg = make_message(sender=sender, sender_id=4)

        sid, name = _get_sender_info(msg)

        assert sid == "4"
        assert name == "4"

    def test_channel_sender(self) -> None:
        """Channel sender returns channel id and title."""
        sender = make_channel(channel_id=500, title="My Channel")
        msg = make_message(sender=sender, sender_id=500)

        sid, name = _get_sender_info(msg)

        assert sid == "500"
        assert name == "My Channel"

    def test_chat_sender(self) -> None:
        """Chat sender returns chat id and title."""
        sender = make_chat(chat_id=600, title="Group Chat")
        msg = make_message(sender=sender, sender_id=600)

        sid, name = _get_sender_info(msg)

        assert sid == "600"
        assert name == "Group Chat"

    def test_none_sender_uses_sender_id(self) -> None:
        """None sender with a valid sender_id falls back to that id."""
        msg = make_message(sender=None, sender_id=999)

        sid, name = _get_sender_info(msg)

        assert sid == "999"
        assert name == "Unknown"

    def test_none_sender_uses_peer_user_id(self) -> None:
        """None sender with no sender_id falls back to peer_id.user_id."""
        msg = make_message(sender=None, sender_id=None)
        msg.peer_id.user_id = 777
        msg.peer_id.channel_id = None

        sid, name = _get_sender_info(msg)

        assert sid == "777"
        assert name == "Unknown"

    def test_none_sender_uses_peer_channel_id(self) -> None:
        """None sender with no sender_id or user_id falls back to channel_id."""
        msg = make_message(sender=None, sender_id=None)
        msg.peer_id.user_id = None
        msg.peer_id.channel_id = 888

        sid, name = _get_sender_info(msg)

        assert sid == "888"
        assert name == "Unknown"

    def test_none_sender_completely_unknown(self) -> None:
        """None sender with no IDs at all returns 'unknown'."""
        msg = make_message(sender=None, sender_id=None)
        msg.peer_id.user_id = None
        msg.peer_id.channel_id = None

        sid, name = _get_sender_info(msg)

        assert sid == "unknown"
        assert name == "Unknown"

    def test_unknown_sender_type_falls_back(self) -> None:
        """An unrecognised sender type returns sender_id string and 'Unknown'."""
        sender = MagicMock()  # not spec'd to any known type
        msg = make_message(sender=sender, sender_id=321)

        sid, name = _get_sender_info(msg)

        assert sid == "321"
        assert name == "Unknown"


# ---------------------------------------------------------------------------
# _get_chat_info
# ---------------------------------------------------------------------------


class TestGetChatInfo:
    """Tests for _get_chat_info()."""

    def test_user_entity_full_name(self) -> None:
        """Dialog with User entity returns concatenated full name."""
        entity = make_user(user_id=1, first_name="Carol", last_name="Danvers", username="carol")
        dialog = make_dialog(dialog_id=1, name="Carol Danvers", entity=entity)

        chat_id, chat_name = _get_chat_info(dialog)

        assert chat_id == "1"
        assert chat_name == "Carol Danvers"

    def test_user_entity_name_only_first(self) -> None:
        """User entity with only first_name returns first name."""
        entity = make_user(user_id=2, first_name="Dave", last_name="", username="dave")
        dialog = make_dialog(dialog_id=2, name="Dave", entity=entity)

        _, chat_name = _get_chat_info(dialog)

        assert chat_name == "Dave"

    def test_user_entity_falls_back_to_username(self) -> None:
        """User entity with no names falls back to username."""
        entity = make_user(user_id=3, first_name="", last_name="", username="noname")
        dialog = make_dialog(dialog_id=3, name="noname", entity=entity)

        _, chat_name = _get_chat_info(dialog)

        assert chat_name == "noname"

    def test_user_entity_falls_back_to_chat_id(self) -> None:
        """User entity with no name or username falls back to chat_id string."""
        entity = make_user(user_id=10, first_name="", last_name="", username="")
        dialog = make_dialog(dialog_id=10, entity=entity)

        chat_id, chat_name = _get_chat_info(dialog)

        assert chat_id == "10"
        assert chat_name == "10"

    def test_channel_entity(self) -> None:
        """Dialog with Channel entity returns channel title."""
        entity = make_channel(channel_id=200, title="News Channel")
        dialog = make_dialog(dialog_id=200, name="News Channel", entity=entity)

        chat_id, chat_name = _get_chat_info(dialog)

        assert chat_id == "200"
        assert chat_name == "News Channel"

    def test_chat_entity(self) -> None:
        """Dialog with Chat entity returns chat title."""
        entity = make_chat(chat_id=300, title="Family Group")
        dialog = make_dialog(dialog_id=300, name="Family Group", entity=entity)

        chat_id, chat_name = _get_chat_info(dialog)

        assert chat_id == "300"
        assert chat_name == "Family Group"

    def test_fallback_to_dialog_name(self) -> None:
        """Unknown entity type falls back to dialog.name."""
        entity = MagicMock()  # not spec'd to any known type
        dialog = make_dialog(dialog_id=400, name="Fallback Name", entity=entity)

        chat_id, chat_name = _get_chat_info(dialog)

        assert chat_id == "400"
        assert chat_name == "Fallback Name"

    def test_fallback_to_chat_id_when_no_dialog_name(self) -> None:
        """Unknown entity with no dialog.name falls back to chat_id string."""
        entity = MagicMock()
        dialog = make_dialog(dialog_id=500, name=None, entity=entity)

        chat_id, chat_name = _get_chat_info(dialog)

        assert chat_id == "500"
        assert chat_name == "500"


# ---------------------------------------------------------------------------
# _classify_media
# ---------------------------------------------------------------------------


class TestClassifyMedia:
    """Tests for _classify_media()."""

    def test_no_media_returns_text(self) -> None:
        """Message with no media returns TEXT type and no attachment."""
        msg = make_message(media=None)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.TEXT
        assert attachment is None

    def test_photo_media(self) -> None:
        """MessageMediaPhoto returns IMAGE type with jpeg mime and file id."""
        media = MagicMock(spec=types.MessageMediaPhoto)
        msg = make_message(msg_id=10, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.IMAGE
        assert attachment is not None
        assert attachment.mime_type == "image/jpeg"
        assert attachment.platform_file_id == "10"

    def test_document_sticker(self) -> None:
        """Document with sticker attribute returns STICKER type."""
        doc = MagicMock(spec=types.Document)
        doc.mime_type = "image/webp"
        doc.size = 512
        sticker_attr = MagicMock(spec=types.DocumentAttributeSticker)
        doc.attributes = [sticker_attr]

        media = MagicMock(spec=types.MessageMediaDocument)
        media.document = doc
        msg = make_message(msg_id=20, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.STICKER
        assert attachment is not None
        assert attachment.mime_type == "image/webp"

    def test_document_audio_ogg(self) -> None:
        """Document with audio/ogg mime type returns AUDIO type."""
        doc = MagicMock(spec=types.Document)
        doc.mime_type = "audio/ogg"
        doc.size = 1024
        audio_attr = MagicMock(spec=types.DocumentAttributeAudio)
        audio_attr.duration = 43
        doc.attributes = [audio_attr]

        media = MagicMock(spec=types.MessageMediaDocument)
        media.document = doc
        msg = make_message(msg_id=30, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.AUDIO
        assert attachment is not None
        assert attachment.duration_seconds == 43
        assert attachment.size_bytes == 1024

    def test_document_audio_application_ogg(self) -> None:
        """Document with application/ogg mime type also returns AUDIO type."""
        doc = MagicMock(spec=types.Document)
        doc.mime_type = "application/ogg"
        doc.size = 2048
        doc.attributes = []

        media = MagicMock(spec=types.MessageMediaDocument)
        media.document = doc
        msg = make_message(msg_id=31, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.AUDIO

    def test_document_video(self) -> None:
        """Document with video/* mime type returns VIDEO type."""
        doc = MagicMock(spec=types.Document)
        doc.mime_type = "video/mp4"
        doc.size = 5_000_000
        video_attr = MagicMock(spec=types.DocumentAttributeVideo)
        video_attr.duration = 120
        doc.attributes = [video_attr]

        media = MagicMock(spec=types.MessageMediaDocument)
        media.document = doc
        msg = make_message(msg_id=40, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.VIDEO
        assert attachment is not None
        assert attachment.duration_seconds == 120

    def test_document_generic_with_filename(self) -> None:
        """Generic document (PDF) returns DOCUMENT type with filename."""
        doc = MagicMock(spec=types.Document)
        doc.mime_type = "application/pdf"
        doc.size = 300_000
        filename_attr = MagicMock(spec=types.DocumentAttributeFilename)
        filename_attr.file_name = "report.pdf"
        doc.attributes = [filename_attr]

        media = MagicMock(spec=types.MessageMediaDocument)
        media.document = doc
        msg = make_message(msg_id=50, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.DOCUMENT
        assert attachment is not None
        assert attachment.filename == "report.pdf"
        assert attachment.mime_type == "application/pdf"

    def test_document_not_a_document_type(self) -> None:
        """MessageMediaDocument whose .document is not a types.Document instance."""
        media = MagicMock(spec=types.MessageMediaDocument)
        media.document = MagicMock()  # not spec=types.Document

        msg = make_message(msg_id=55, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.DOCUMENT
        assert attachment is not None
        assert attachment.platform_file_id == "55"

    def test_geo_location(self) -> None:
        """MessageMediaGeo returns LOCATION type with no attachment."""
        media = MagicMock(spec=types.MessageMediaGeo)
        msg = make_message(media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.LOCATION
        assert attachment is None

    def test_venue_location(self) -> None:
        """MessageMediaVenue returns LOCATION type with no attachment."""
        media = MagicMock(spec=types.MessageMediaVenue)
        msg = make_message(media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.LOCATION
        assert attachment is None

    def test_geo_live_location(self) -> None:
        """MessageMediaGeoLive returns LOCATION type with no attachment."""
        media = MagicMock(spec=types.MessageMediaGeoLive)
        msg = make_message(media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.LOCATION
        assert attachment is None

    def test_contact_media(self) -> None:
        """MessageMediaContact is treated as TEXT."""
        media = MagicMock(spec=types.MessageMediaContact)
        msg = make_message(media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.TEXT
        assert attachment is None

    def test_unsupported_media(self) -> None:
        """MessageMediaUnsupported returns UNKNOWN with attachment."""
        media = MagicMock(spec=types.MessageMediaUnsupported)
        msg = make_message(msg_id=60, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.UNKNOWN
        assert attachment is not None
        assert attachment.platform_file_id == "60"

    def test_unknown_media_type_falls_back_to_text(self) -> None:
        """Unrecognised media type (e.g. web page preview) falls back to TEXT."""
        media = MagicMock(spec=types.MessageMediaWebPage)
        msg = make_message(media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.TEXT
        assert attachment is None

    def test_document_no_duration_on_audio_attr(self) -> None:
        """Audio attribute with duration=None leaves duration_seconds as None."""
        doc = MagicMock(spec=types.Document)
        doc.mime_type = "audio/mpeg"
        doc.size = 500
        audio_attr = MagicMock(spec=types.DocumentAttributeAudio)
        audio_attr.duration = None
        doc.attributes = [audio_attr]

        media = MagicMock(spec=types.MessageMediaDocument)
        media.document = doc
        msg = make_message(msg_id=70, media=media)

        msg_type, attachment = _classify_media(msg)

        assert msg_type == MessageType.AUDIO
        assert attachment is not None
        assert attachment.duration_seconds is None


# ---------------------------------------------------------------------------
# _map_message
# ---------------------------------------------------------------------------


class TestMapMessage:
    """Tests for _map_message()."""

    def _make_dialog_with_user(self) -> MagicMock:
        """Helper: create a dialog whose entity is a User."""
        entity = make_user(user_id=1, first_name="Alice", last_name="Smith")
        return make_dialog(dialog_id=1, name="Alice Smith", entity=entity)

    def test_returns_none_for_non_message(self) -> None:
        """Non-Message objects (e.g. MessageService) return None."""
        service_msg = MagicMock(spec=types.MessageService)
        dialog = self._make_dialog_with_user()

        result = _map_message(service_msg, dialog)

        assert result is None

    def test_returns_none_for_message_action(self) -> None:
        """MessageEmpty objects return None."""
        empty_msg = MagicMock(spec=types.MessageEmpty)
        dialog = self._make_dialog_with_user()

        result = _map_message(empty_msg, dialog)

        assert result is None

    def test_basic_text_message(self) -> None:
        """A standard text message maps all fields correctly."""
        sender = make_user(user_id=1, first_name="Alice", last_name="Smith")
        dialog = self._make_dialog_with_user()
        msg = make_message(
            msg_id=100,
            sender=sender,
            sender_id=1,
            text="Hello world",
            out=False,
            date=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        )

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.platform == Platform.TELEGRAM
        assert result.platform_message_id == "100"
        assert result.chat_id == "1"
        assert result.chat_name == "Alice Smith"
        assert result.sender_id == "1"
        assert result.sender_name == "Alice Smith"
        assert result.is_outgoing is False
        assert result.message_type == MessageType.TEXT
        assert result.text == "Hello world"
        assert result.attachment is None
        assert result.timestamp == datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        assert result.reply_to_id is None

    def test_outgoing_message(self) -> None:
        """is_outgoing flag is correctly propagated."""
        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()
        msg = make_message(sender=sender, sender_id=1, out=True)

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.is_outgoing is True

    def test_empty_text_becomes_none(self) -> None:
        """Empty string text is stored as None."""
        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()
        msg = make_message(sender=sender, sender_id=1, text="")

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.text is None

    def test_reply_to_message_id_extracted(self) -> None:
        """reply_to_msg_id is extracted and stored as reply_to_id string."""
        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()

        reply_to = MagicMock()
        reply_to.reply_to_msg_id = 77

        msg = make_message(sender=sender, sender_id=1, reply_to=reply_to)

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.reply_to_id == "77"

    def test_reply_to_none_gives_no_reply_id(self) -> None:
        """Message with no reply_to has reply_to_id of None."""
        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()
        msg = make_message(sender=sender, sender_id=1, reply_to=None)

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.reply_to_id is None

    def test_reply_to_without_msg_id_attr_gives_no_reply_id(self) -> None:
        """reply_to object without reply_to_msg_id attr gives None reply_to_id."""
        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()

        reply_to = MagicMock(spec=[])  # no attributes at all

        msg = make_message(sender=sender, sender_id=1, reply_to=reply_to)

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.reply_to_id is None

    def test_naive_datetime_gets_utc_tzinfo(self) -> None:
        """A naive (no tzinfo) datetime on msg.date is assumed UTC."""
        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()
        naive_date = datetime(2024, 6, 1, 8, 0)  # no tzinfo
        msg = make_message(sender=sender, sender_id=1, date=naive_date)

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.timestamp.tzinfo is not None
        assert result.timestamp == datetime(2024, 6, 1, 8, 0, tzinfo=timezone.utc)

    def test_aware_datetime_converted_to_utc(self) -> None:
        """An aware datetime in another timezone is converted to UTC."""
        import datetime as dt

        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()

        # UTC+5 offset
        tz_plus5 = dt.timezone(dt.timedelta(hours=5))
        aware_date = datetime(2024, 6, 1, 13, 0, tzinfo=tz_plus5)  # 08:00 UTC
        msg = make_message(sender=sender, sender_id=1, date=aware_date)

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.timestamp == datetime(2024, 6, 1, 8, 0, tzinfo=timezone.utc)

    def test_photo_message_mapped(self) -> None:
        """A photo message maps to IMAGE type with an attachment."""
        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()

        media = MagicMock(spec=types.MessageMediaPhoto)
        msg = make_message(msg_id=200, sender=sender, sender_id=1, text="", media=media)

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.message_type == MessageType.IMAGE
        assert result.attachment is not None
        assert result.attachment.platform_file_id == "200"

    def test_audio_message_mapped(self) -> None:
        """A voice note message maps to AUDIO type with duration in attachment."""
        sender = make_user(user_id=1, first_name="Alice")
        dialog = self._make_dialog_with_user()

        doc = MagicMock(spec=types.Document)
        doc.mime_type = "audio/ogg"
        doc.size = 8192
        audio_attr = MagicMock(spec=types.DocumentAttributeAudio)
        audio_attr.duration = 15
        doc.attributes = [audio_attr]

        media = MagicMock(spec=types.MessageMediaDocument)
        media.document = doc
        msg = make_message(msg_id=300, sender=sender, sender_id=1, text="", media=media)

        result = _map_message(msg, dialog)

        assert result is not None
        assert result.message_type == MessageType.AUDIO
        assert result.attachment is not None
        assert result.attachment.duration_seconds == 15
