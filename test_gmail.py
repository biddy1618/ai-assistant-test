"""
Quick test: sync Gmail and print the last 10 emails stored.
Run with: python3 test_gmail.py
"""

import asyncio
from pathlib import Path

from src.store.database import MessageStore
from src.connectors.gmail_connector import GmailConnector


async def main():
    store = MessageStore(db_path=Path("/tmp/test_sister_agent.db"))
    await store.connect()

    connector = GmailConnector(store)
    ok = await connector.authenticate()
    if not ok:
        print("Authentication failed.")
        return

    print("Syncing last 30 days of Gmail...")
    count = await connector.sync(full=True)
    print(f"Synced {count} emails.\n")

    messages = await store.get_recent_messages(hours=24 * 30, limit=10)
    print(f"Last {len(messages)} emails:")
    for msg in messages:
        print(f"  [{msg.timestamp.strftime('%Y-%m-%d')}] {msg.sender_name}: {msg.subject}")

    await connector.disconnect()
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
