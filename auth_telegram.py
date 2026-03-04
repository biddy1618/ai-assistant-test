"""
Telegram user account setup script.

Run this once to authenticate your Telegram account and generate config/telegram.session.
After that, the TelegramConnector will reuse the session automatically.

Usage:
    python auth_telegram.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from telethon import TelegramClient

SESSION_FILE = Path("config/telegram.session")


async def main() -> None:
    """Interactive Telegram auth flow — runs once to create the session file."""
    load_dotenv()

    api_id_str = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    phone = os.environ.get("TELEGRAM_PHONE", "").strip()

    missing = [name for name, val in [
        ("TELEGRAM_API_ID", api_id_str),
        ("TELEGRAM_API_HASH", api_hash),
        ("TELEGRAM_PHONE", phone),
    ] if not val]

    if missing:
        logger.error(
            "Missing required environment variables: {}. "
            "Copy .env.example to .env and fill them in.",
            ", ".join(missing),
        )
        sys.exit(1)

    try:
        api_id = int(api_id_str)
    except ValueError:
        logger.error("TELEGRAM_API_ID must be an integer, got: {!r}", api_id_str)
        sys.exit(1)

    # Ensure config directory exists
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Telethon appends ".session" automatically — strip the suffix before passing
    session_name = str(SESSION_FILE.with_suffix(""))

    logger.info("Starting Telegram authentication for phone {}...", phone)
    logger.info("Session will be saved to: {}", SESSION_FILE)

    client = TelegramClient(session_name, api_id, api_hash)

    try:
        # client.start() handles the full interactive flow:
        # prompts for SMS code (and optionally 2FA password)
        await client.start(phone=phone)

        me = await client.get_me()
        display = me.username or me.first_name or str(me.id)
        logger.info("Successfully authenticated as @{}", display)
        print(f"\nAuthenticated as: @{display} (id={me.id})")
        print(f"Session saved to: {SESSION_FILE}")
        print("\nYou can now run: python main.py")
    except Exception:
        logger.exception("Authentication failed.")
        sys.exit(1)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
