"""
Sister AI Agent — main entrypoint.

Usage:
    python main.py            # normal run
    python main.py --full-sync  # force full re-sync on startup
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

# ---------------------------------------------------------------------------
# Logging — configure before any other imports that use loguru
# ---------------------------------------------------------------------------

logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(exist_ok=True)

logger.add(
    str(_LOG_DIR / "agent.log"),
    rotation="10 MB",
    retention="7 days",
    level="DEBUG",
)

# ---------------------------------------------------------------------------
# Late imports — after logging is configured
# ---------------------------------------------------------------------------

from src.agent.calendar import CalendarManager  # noqa: E402
from src.agent.core import AgentCore  # noqa: E402
from src.bot.handlers import SisterBot, set_agent  # noqa: E402
from src.connectors.gmail_connector import GmailConnector  # noqa: E402
from src.connectors.telegram_connector import TelegramConnector  # noqa: E402
from src.store.database import DEFAULT_DB_PATH, MessageStore  # noqa: E402

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _require(name: str) -> str:
    """Return the value of a required env var, or exit with a clear error."""
    value = os.environ.get(name, "").strip()
    if not value:
        logger.error("Required environment variable '{}' is not set. Check your .env file.", name)
        sys.exit(1)
    return value


def _optional(name: str, default: str) -> str:
    """Return env var value, falling back to *default* if not set."""
    return os.environ.get(name, "").strip() or default


# ---------------------------------------------------------------------------
# Main coroutine
# ---------------------------------------------------------------------------


async def main() -> None:
    """Initialise all components, wire them together, and run the bot."""

    # 1. Load .env
    load_dotenv()

    # 2. Parse CLI args
    parser = argparse.ArgumentParser(description="Sister AI Agent")
    parser.add_argument(
        "--full-sync",
        action="store_true",
        help="Force a full re-sync of all connectors on startup.",
    )
    args = parser.parse_args()

    # 3. Validate required env vars
    anthropic_api_key = _require("ANTHROPIC_API_KEY")
    bot_token = _require("TELEGRAM_BOT_TOKEN")
    allowed_user_id = int(_require("TELEGRAM_ALLOWED_USER_ID"))
    tg_api_id = int(_require("TELEGRAM_API_ID"))
    tg_api_hash = _require("TELEGRAM_API_HASH")
    tg_phone = _require("TELEGRAM_PHONE")

    # 4. Optional env vars with defaults that match the connector defaults
    credentials_path = Path(_optional("GOOGLE_CREDENTIALS_PATH", "config/credentials.json"))
    token_path = Path(_optional("GOOGLE_TOKEN_PATH", "config/token.json"))
    db_path_str = _optional("DB_PATH", "")
    db_path = Path(db_path_str).expanduser() if db_path_str else DEFAULT_DB_PATH

    logger.info("Sister AI Agent starting up...")
    logger.info("DB path: {}", db_path)

    # -----------------------------------------------------------------------
    # Component initialisation
    # -----------------------------------------------------------------------

    store = MessageStore(db_path=db_path)
    gmail = GmailConnector(store, credentials_file=credentials_path, token_file=token_path)
    telegram = TelegramConnector(
        store,
        api_id=tg_api_id,
        api_hash=tg_api_hash,
        phone=tg_phone,
    )
    connectors = [gmail, telegram]

    cal: CalendarManager | None = None

    try:
        # 5. Open the database
        await store.connect()
        logger.info("Database connected.")

        # 6. Authenticate each connector (failures are logged, not fatal)
        for connector in connectors:
            platform_name = connector.platform.value
            try:
                success = await connector.authenticate()
                if success:
                    logger.info("Connector '{}' authenticated successfully.", platform_name)
                else:
                    logger.warning(
                        "Connector '{}' authentication failed — it will be skipped.", platform_name
                    )
            except Exception:
                logger.exception("Unexpected error authenticating connector '{}'.", platform_name)

        # 7. Build agent
        agent = AgentCore(store=store, api_key=anthropic_api_key, model="claude-sonnet-4-6")
        logger.info("AgentCore initialised (model=claude-sonnet-4-6).")

        # 8. Build CalendarManager only if the token file already exists
        if token_path.exists():
            cal = CalendarManager(token_file=token_path, api_key=anthropic_api_key)
            logger.info("CalendarManager initialised.")
        else:
            logger.warning(
                "Google token file not found at '{}' — CalendarManager disabled. "
                "Run auth_google.py first.",
                token_path,
            )

        # 9. Inject agent into bot handlers
        set_agent(agent)

        # 10. Build the bot
        bot = SisterBot(
            token=bot_token,
            sister_id=allowed_user_id,
            store=store,
            connectors=connectors,
            calendar_manager=cal,
        )

        # 11. Optional full sync before starting
        if args.full_sync:
            logger.info("--full-sync requested, syncing all connectors before starting bot...")
            for connector in connectors:
                platform_name = connector.platform.value
                try:
                    count = await connector.sync(full=True)
                    logger.info("Full sync '{}': {} messages.", platform_name, count)
                except Exception:
                    logger.exception("Full sync failed for '{}'.", platform_name)

        # 12. Run the bot (blocking until interrupted)
        logger.info("Starting SisterBot...")
        await bot.run()

    finally:
        # Graceful shutdown — disconnect everything
        logger.info("Shutting down...")
        for connector in connectors:
            platform_name = connector.platform.value
            try:
                await connector.disconnect()
                logger.info("Connector '{}' disconnected.", platform_name)
            except Exception:
                logger.exception("Error disconnecting connector '{}'.", platform_name)

        await store.close()
        logger.info("Database closed. Goodbye.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())
