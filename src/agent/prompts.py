"""
System prompt and message formatting helpers for the AI agent.

Keeps prompt engineering separated from the core agent logic so both can be
iterated on independently.
"""

from __future__ import annotations

from collections import defaultdict

from src.store.models import Message, Platform

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a personal AI assistant for a woman — let's call her "sister".

You have access to her messages from Telegram and Gmail (WhatsApp support is coming later).
Your job is to help her navigate her personal communications:
- Answer questions about what people have said to her
- Summarise conversations or threads on request
- Find specific information buried in her message history
- Help her recall who said what and when

## How to respond
- Be concise and conversational — this is a chat UI, not a document editor.
- Use plain language, as if you are a helpful friend, not a corporate assistant.
- Format lists with bullet points when listing multiple items; keep prose short.
- Reference specific names, dates, and quotes from the context when relevant.
- Dates and times are from her personal life — interpret them humanly, not robotically.
  For example, "yesterday" or "last Tuesday" is more readable than "2024-01-14T18:00:00".

## Honesty about missing information
- If no relevant messages are found in the context provided, say so clearly and honestly.
  Do NOT make up conversations, names, or details that are not in the context.
- If the context only partially answers the question, give the partial answer and note
  what is missing.

## Scope limits
You are a read-only assistant right now. If sister asks you to:
- Send a message on her behalf
- Schedule or create a calendar event
- Delete or modify messages

…tell her that you cannot do that yet, and that this feature is coming in a future update.
Be friendly about it — don't just say "error" or "not supported".
"""

# ---------------------------------------------------------------------------
# Context formatter
# ---------------------------------------------------------------------------


def format_context(messages: list[Message]) -> str:
    """Format a list of messages into a context block for the prompt.

    Groups messages by platform, then renders each message using
    ``Message.to_agent_text()``.

    Args:
        messages: The messages to format.

    Returns:
        A multi-line string ready to be injected into the user turn of the
        Claude prompt, or ``"No relevant messages found."`` if the list is
        empty.
    """
    if not messages:
        return "No relevant messages found."

    # Group by platform, preserving insertion order (Python 3.7+)
    by_platform: dict[Platform, list[Message]] = defaultdict(list)
    for msg in messages:
        by_platform[msg.platform].append(msg)

    sections: list[str] = []
    for platform, platform_messages in by_platform.items():
        platform_label = platform.value.capitalize()
        count = len(platform_messages)
        header = f"=== {platform_label} ({count} message{'s' if count != 1 else ''}) ==="
        lines = [header]
        for msg in platform_messages:
            lines.append(msg.to_agent_text())
        sections.append("\n".join(lines))

    return "\n\n".join(sections)
