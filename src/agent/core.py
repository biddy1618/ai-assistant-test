"""
Core AI agent that answers natural-language questions using the message store as context.

Uses the Anthropic Python SDK (synchronous client wrapped in asyncio.to_thread so the
rest of the codebase stays fully async).
"""

from __future__ import annotations

import asyncio

import anthropic
from loguru import logger

from src.agent.prompts import SYSTEM_PROMPT, format_context
from src.store.database import MessageStore
from src.store.models import Message


class AgentCore:
    """
    Retrieval-augmented AI agent backed by Claude.

    On each ``ask()`` call the agent:
    1. Retrieves relevant messages from the store (FTS search + recent messages).
    2. Deduplicates and trims the result set.
    3. Formats the messages as context.
    4. Calls the Claude API and returns the plain-text reply.
    """

    def __init__(
        self,
        store: MessageStore,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        max_context_messages: int = 30,
    ) -> None:
        """
        Initialise the agent.

        Args:
            store: An open ``MessageStore`` instance used for context retrieval.
            api_key: Anthropic API key.
            model: Claude model ID to use for responses.
            max_context_messages: Maximum number of messages to include in the
                Claude context window per request.
        """
        self._store = store
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_context_messages = max_context_messages

    async def ask(self, question: str) -> str:
        """
        Answer a natural-language question using message history as context.

        Retrieves relevant messages via FTS search and a recent-messages window,
        merges and deduplicates them, then calls the Claude API.

        Args:
            question: The plain-text question from the sister.

        Returns:
            A plain-text reply suitable for sending in Telegram.
        """
        logger.info(
            "Agent asked: {!r} (model={})",
            question[:100],
            self.model,
        )

        # 1. Run FTS search and recent-messages fetch in parallel
        search_results, recent_messages = await asyncio.gather(
            self._store.search(question, limit=20),
            self._store.get_recent_messages(hours=24, limit=20),
        )

        # 2. Merge and deduplicate by platform_message_id, most recent first
        seen: set[str] = set()
        merged: list[Message] = []
        for msg in search_results + recent_messages:
            key = f"{msg.platform.value}:{msg.platform_message_id}"
            if key not in seen:
                seen.add(key)
                merged.append(msg)

        # Sort descending by timestamp, then take the top N
        merged.sort(key=lambda m: m.timestamp, reverse=True)
        context_messages = merged[: self.max_context_messages]

        logger.debug(
            "Context: {} messages ({} from search, {} recent, {} after dedup+trim)",
            len(context_messages),
            len(search_results),
            len(recent_messages),
            len(merged),
        )

        # 3. Format context block
        context = format_context(context_messages)

        # 4. Call Claude (synchronous SDK wrapped in a thread)
        user_content = (
            f"Context from message history:\n\n{context}\n\nQuestion: {question}"
        )

        def _call_claude() -> str:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": user_content,
                    }
                ],
            )
            return response.content[0].text

        reply: str = await asyncio.to_thread(_call_claude)

        logger.info(
            "Agent replied ({} context messages, model={})",
            len(context_messages),
            self.model,
        )
        return reply
