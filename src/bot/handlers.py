"""
Telegram bot handlers for the Sister AI Assistant.

Provides a SisterBot class that wraps python-telegram-bot's Application and
wires up all command/message handlers plus a background hourly sync job.

Only the one allowed user (sister's Telegram user ID) ever receives responses.
All other users are silently ignored.
"""

from __future__ import annotations

from loguru import logger
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.agent.calendar import CalendarManager, EventProposal
from src.agent.core import AgentCore
from src.connectors.base import BaseConnector
from src.store.database import MessageStore

# ---------------------------------------------------------------------------
# AI agent — injected at startup by the main entry-point
# ---------------------------------------------------------------------------

_agent: AgentCore | None = None


def set_agent(agent: AgentCore) -> None:
    """Called once at startup to inject the real AI agent.

    Args:
        agent: An initialised ``AgentCore`` instance.
    """
    global _agent
    _agent = agent


async def _ask_agent(question: str, store: MessageStore) -> str:
    """Route a question to the AI agent.

    Falls back gracefully if the agent has not been initialised yet.

    Args:
        question: The plain-text question from the sister.
        store: The message store (kept for signature compatibility with callers).

    Returns:
        A plain-text reply to send back to the sister.
    """
    if _agent is None:
        return "AI agent not initialised yet."
    return await _agent.ask(question)


# ---------------------------------------------------------------------------
# SisterBot
# ---------------------------------------------------------------------------


class SisterBot:
    """
    Telegram bot that serves as the sister's AI assistant interface.

    Handles:
    - /start — welcome message
    - /sync  — manual sync of all connectors
    - Plain text messages — forwarded to the AI agent placeholder
    - Background hourly sync job
    - Silent ignore of all users other than the authorised sister
    """

    def __init__(
        self,
        token: str,
        sister_id: int,
        store: MessageStore,
        connectors: list[BaseConnector],
        calendar_manager: CalendarManager | None = None,
    ) -> None:
        """
        Initialise the bot.

        Args:
            token: Telegram Bot API token.
            sister_id: The Telegram user ID of the sister. All other users are ignored.
            store: Opened MessageStore instance used by the AI agent.
            connectors: List of platform connectors to sync.
            calendar_manager: Optional CalendarManager for event detection and creation.
        """
        self._token = token
        self._sister_id = sister_id
        self._store = store
        self._connectors = connectors
        self._calendar: CalendarManager | None = calendar_manager
        self._pending_proposal: EventProposal | None = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Build and run the Application until stopped (blocking)."""
        app: Application = ApplicationBuilder().token(self._token).build()

        # Register handlers
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("sync", self._handle_sync))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        # Background sync: first run after 10 s, then every hour
        app.job_queue.run_repeating(
            self._background_sync,
            interval=3600,
            first=10,
        )

        logger.info("SisterBot starting (authorised user id={})", self._sister_id)
        app.run_polling()

    # ------------------------------------------------------------------
    # Auth guard (inline helper)
    # ------------------------------------------------------------------

    def _is_authorised(self, update: Update) -> bool:
        """Return True only if the update comes from the sister's account."""
        user = update.effective_user
        return user is not None and user.id == self._sister_id

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start — send a welcome message to the sister."""
        if not self._is_authorised(update):
            return

        try:
            await update.message.reply_text(
                "Hi! I'm your personal assistant. Ask me anything about your messages."
            )
        except Exception:
            logger.exception("Error in /start handler")
            await update.message.reply_text("Something went wrong, please try again.")

    async def _handle_sync(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /sync — trigger a manual incremental sync across all connectors."""
        if not self._is_authorised(update):
            return

        try:
            await update.message.reply_text("Syncing all connectors, please wait…")

            counts: dict[str, int] = {}
            for connector in self._connectors:
                platform_name = connector.platform.value
                try:
                    new_count = await connector.sync()
                    counts[platform_name] = new_count
                    logger.info(
                        "Manual sync complete for {}: {} new messages",
                        platform_name,
                        new_count,
                    )
                except Exception:
                    logger.exception("Error syncing connector {}", platform_name)
                    counts[platform_name] = -1  # sentinel for error

            # Build a human-readable summary
            lines = ["Sync complete:"]
            for platform, count in counts.items():
                if count == -1:
                    lines.append(f"  • {platform}: error (check logs)")
                else:
                    lines.append(f"  • {platform}: {count} new message(s)")

            await update.message.reply_text("\n".join(lines))

        except Exception:
            logger.exception("Error in /sync handler")
            await update.message.reply_text("Something went wrong, please try again.")

    # ------------------------------------------------------------------
    # Plain-text message handler
    # ------------------------------------------------------------------

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle plain-text messages — pass to the AI agent, reply with result."""
        if not self._is_authorised(update):
            return

        try:
            text = (update.message.text or "").strip().lower()

            # Pending event confirmation flow
            if self._pending_proposal is not None:
                if text in ("yes", "да", "y", "yep", "sure", "ok"):
                    result = await self._calendar.create_event(self._pending_proposal)
                    self._pending_proposal = None
                    await update.message.reply_text(result)
                    return
                elif text in ("no", "нет", "n", "nope", "cancel"):
                    self._pending_proposal = None
                    await update.message.reply_text("OK, skipped.")
                    return
                else:
                    # Not a yes/no — treat as new question, clear pending
                    self._pending_proposal = None

            reply = await _ask_agent(update.message.text or "", self._store)
            await update.message.reply_text(reply)

        except Exception:
            logger.exception("Error in message handler")
            await update.message.reply_text("Something went wrong, please try again.")

    # ------------------------------------------------------------------
    # Background sync job
    # ------------------------------------------------------------------

    async def _notify_events(
        self,
        proposals: list[EventProposal],
        chat_id: int,
        app: Application,
    ) -> None:
        """
        Send an event suggestion to the sister for the first detected event.

        Only the first proposal is surfaced to avoid spamming the chat.
        Sets ``self._pending_proposal`` so the next message can confirm or dismiss it.

        Args:
            proposals: List of EventProposal objects detected in recent messages.
            chat_id: Telegram chat ID to send the notification to.
            app: The running Application instance used to send the message.
        """
        if not proposals or self._calendar is None:
            return
        # Only suggest the first event to avoid spamming
        proposal = proposals[0]
        self._pending_proposal = proposal
        time_str = f" at {proposal.time}" if proposal.time else ""
        msg = (
            f"I noticed an event in your messages:\n"
            f"**{proposal.title}** on {proposal.date}{time_str}\n"
            f"Add to Google Calendar? (yes/no)"
        )
        await app.bot.send_message(chat_id=chat_id, text=msg)

    async def _background_sync(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Periodic background job: sync all connectors every hour.

        After syncing, if new messages arrived and a CalendarManager is configured,
        scans them for calendar events and notifies the sister of any found.
        """
        logger.info("Background sync started")
        total_new = 0
        for connector in self._connectors:
            platform_name = connector.platform.value
            try:
                new_count = await connector.sync()
                total_new += new_count
                logger.info(
                    "Background sync {}: {} new message(s)", platform_name, new_count
                )
            except Exception:
                logger.exception(
                    "Background sync error for connector {}", platform_name
                )

        # Scan recent messages for calendar events if we got anything new
        if self._calendar is not None and total_new > 0:
            try:
                recent = await self._store.get_recent_messages(hours=1, limit=50)
                proposals = await self._calendar.scan_for_events(recent)
                if proposals:
                    await self._notify_events(
                        proposals, self._sister_id, context.application
                    )
            except Exception:
                logger.exception("Error scanning for calendar events")

        logger.info("Background sync finished")
