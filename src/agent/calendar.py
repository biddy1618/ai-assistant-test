"""
Google Calendar integration for the Sister AI Assistant.

CalendarManager uses Claude to scan a batch of messages for calendar events,
then can create those events in Google Calendar via the REST API.

HTTP transport uses google.auth.transport.requests (requests-based) so that
the https_proxy environment variable is respected — same pattern as GmailConnector.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import anthropic
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from loguru import logger
from pydantic import BaseModel

from src.store.models import Message

# Scopes that must have been granted when the token was created
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class EventProposal(BaseModel):
    """A calendar event extracted from message content by Claude."""

    title: str
    date: str  # ISO date string, e.g. "2024-01-20"
    time: str | None  # "19:00" or None if all-day
    duration_minutes: int = 60
    location: str | None = None
    description: str | None = None
    source_platform: str  # e.g. "telegram"
    source_message_id: str


# ---------------------------------------------------------------------------
# CalendarManager
# ---------------------------------------------------------------------------


class CalendarManager:
    """
    Detects calendar events in messages using Claude and creates them in Google Calendar.

    Usage::

        manager = CalendarManager(
            token_file=Path("config/token.json"),
            api_key=os.environ["ANTHROPIC_API_KEY"],
        )
        proposals = await manager.scan_for_events(messages)
        for p in proposals:
            confirmation = await manager.create_event(p)
            print(confirmation)
    """

    def __init__(
        self,
        token_file: Path = Path("config/token.json"),
        api_key: str = "",
        model: str = "claude-sonnet-4-6",
    ) -> None:
        """
        Initialise the CalendarManager.

        Args:
            token_file: Path to the OAuth2 token JSON produced by auth_google.py.
            api_key: Anthropic API key used by Claude for event detection.
            model: Claude model ID to use for scanning messages.
        """
        self._token_file = token_file
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan_for_events(self, messages: list[Message]) -> list[EventProposal]:
        """
        Use Claude to detect calendar events in a batch of messages.

        Args:
            messages: List of Message objects to scan.

        Returns:
            A list of EventProposal objects. May be empty if no events found.
        """
        if not messages:
            return []

        messages_text = "\n".join(msg.to_agent_text() for msg in messages)
        today_iso = date.today().isoformat()

        prompt = f"""You are analyzing messages for calendar events.
Look for any specific meetings, appointments, dinners, calls, deadlines, or events mentioned.

Messages:
{messages_text}

Today's date: {today_iso}

Respond with a JSON array of events found. Each event:
{{
  "title": "...",
  "date": "YYYY-MM-DD",
  "time": "HH:MM or null",
  "duration_minutes": 60,
  "location": "... or null",
  "description": "... or null",
  "source_platform": "...",
  "source_message_id": "..."
}}

If no events found, respond with an empty array [].
Only include concrete, specific events with a clear date — not vague mentions.
Respond with ONLY the JSON array, no other text."""

        def _call_claude() -> str:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()

        raw: str = await asyncio.to_thread(_call_claude)
        logger.debug("CalendarManager scan raw response: {!r}", raw[:300])

        try:
            items: list[dict] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("CalendarManager: Claude returned non-JSON: {!r}", raw[:200])
            return []

        proposals: list[EventProposal] = []
        for item in items:
            try:
                proposals.append(EventProposal(**item))
            except Exception as exc:
                logger.warning("CalendarManager: skipping invalid event item {!r}: {}", item, exc)

        logger.info(
            "CalendarManager.scan_for_events: {} messages → {} proposals",
            len(messages),
            len(proposals),
        )
        return proposals

    async def create_event(self, proposal: EventProposal) -> str:
        """
        Create an event in Google Calendar from an EventProposal.

        Uses the requests-based AuthorizedSession transport so that the
        https_proxy environment variable is respected (same as GmailConnector).

        Args:
            proposal: The EventProposal to materialise in Google Calendar.

        Returns:
            A human-readable confirmation string, e.g.
            "Added to calendar: Dinner with Mom on 2024-01-20"

        Raises:
            RuntimeError: If the token file is missing or the API call fails.
        """
        if not self._token_file.exists():
            raise RuntimeError(
                f"Token file not found: {self._token_file}. Run auth_google.py first."
            )

        creds = Credentials.from_authorized_user_file(str(self._token_file), SCOPES)
        session = google.auth.transport.requests.AuthorizedSession(creds)

        # Refresh token if expired
        if not creds.valid and creds.expired and creds.refresh_token:
            logger.info("CalendarManager: refreshing expired token…")
            creds.refresh(google.auth.transport.requests.Request(session=session))
            self._token_file.write_text(creds.to_json())
            logger.info("CalendarManager: token refreshed and saved.")

        # Calculate end time
        start_time_str = proposal.time or "09:00"
        start_dt = datetime.strptime(f"{proposal.date}T{start_time_str}", "%Y-%m-%dT%H:%M")
        end_dt = start_dt + timedelta(minutes=proposal.duration_minutes)
        end_time_str = end_dt.strftime("%H:%M")

        event_body: dict = {
            "summary": proposal.title,
            "start": {
                "dateTime": f"{proposal.date}T{start_time_str}:00",
                "timeZone": "UTC",
            },
            "end": {
                "dateTime": f"{proposal.date}T{end_time_str}:00",
                "timeZone": "UTC",
            },
        }
        if proposal.location:
            event_body["location"] = proposal.location
        if proposal.description:
            event_body["description"] = proposal.description

        def _post_event() -> None:
            resp = session.post(CALENDAR_EVENTS_URL, json=event_body)
            resp.raise_for_status()
            return resp.json()

        try:
            created = await asyncio.to_thread(_post_event)
            logger.info(
                "CalendarManager: created event '{}' on {} (Google id={})",
                proposal.title,
                proposal.date,
                created.get("id", "?"),
            )
        except Exception as exc:
            logger.error(
                "CalendarManager: failed to create event '{}': {}",
                proposal.title,
                exc,
            )
            raise

        return f"Added to calendar: {proposal.title} on {proposal.date}"
