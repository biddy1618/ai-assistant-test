# Sister AI Agent — Project Plan

## Overview
A personal AI assistant that gives read-only access to WhatsApp, Telegram, and Gmail messages — plus Google Calendar write access. Your sister interacts with it via a Telegram bot. Runs locally on her laptop.

## Architecture

```
┌─────────────────── Data Sources (Read-Only) ───────────────────┐
│                                                                 │
│   [WhatsApp Personal]   [Telegram Personal]   [Gmail Inbox]    │
│     (Baileys/WWebJS)       (Telethon)        (Google API)      │
│          │                     │                   │            │
└──────────┼─────────────────────┼───────────────────┼────────────┘
           │                     │                   │
           ▼                     ▼                   ▼
    ┌──────────────────────────────────────────────────────┐
    │              Message Store (SQLite + FTS5)            │
    │  - Unified schema across all platforms                │
    │  - Full-text search index                             │
    │  - Incremental sync (only fetch new messages)         │
    └──────────────────────┬───────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────┐
    │              AI Agent (Claude via Anthropic API)       │
    │  - Summarization                                      │
    │  - Question answering over message history            │
    │  - Search / retrieval                                 │
    │  - Alert classification                               │
    │  - Calendar event extraction                          │
    └──────────────────────┬───────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼                         ▼
    ┌──────────────────┐    ┌────────────────────┐
    │  Telegram Bot UI  │    │  Google Calendar    │
    │  (python-telegram │    │  (Write access)     │
    │   -bot library)   │    │                     │
    └──────────────────┘    └────────────────────┘
```

## Tech Stack
- **Language**: Python 3.11+
- **LLM**: Anthropic API (Claude Sonnet for cost-efficiency, Opus for complex queries)
- **Database**: SQLite with FTS5 extension (full-text search)
- **WhatsApp**: whatsapp-web.js via Baileys (or Python bridge) — TBD after research
- **Telegram client**: Telethon (user account session for reading personal messages)
- **Telegram bot**: python-telegram-bot (for the UI bot your sister talks to)
- **Gmail**: google-api-python-client with gmail.readonly scope
- **Calendar**: google-api-python-client with calendar.events scope
- **Config**: .env file for secrets, YAML for preferences

## Modules

### Module 1: Project Setup & Message Store ← START HERE
- Python project with proper dependency management (poetry or pip)
- SQLite database schema for unified message storage
- Base connector interface (abstract class all connectors implement)

### Module 2: Gmail Connector
- Google Cloud project setup (OAuth consent screen, credentials)
- Gmail API read-only connector
- Incremental sync (using historyId or after-date filtering)
- Store emails in unified schema

### Module 3: Telegram Connector
- Telethon user client session (requires phone number auth)
- Read personal messages from selected chats
- Incremental sync
- Store in unified schema

### Module 4: WhatsApp Connector
- Research best Python-compatible approach (Baileys via subprocess, or neonbit-whatsapp, etc.)
- QR code auth flow
- Read personal messages
- Session persistence (so she doesn't re-scan QR every time)
- Store in unified schema

### Module 5: Telegram Bot Interface
- Create bot via @BotFather
- Command handlers: /summary, /search, /ask
- Natural language routing to agent

### Module 6: AI Agent Core
- Anthropic API integration
- Context building from message store
- Summarization prompt
- Q&A over message history (RAG-lite with FTS5)
- Important message classification / alerts

### Module 7: Google Calendar Integration
- Calendar API write access
- Event extraction from messages (LLM-powered)
- Confirmation flow before creating events

### Module 8: Polish & Deployment
- Systemd service or launch-on-login script for her laptop
- Error handling & reconnection logic
- Logging
- Simple setup script for first-time config

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| WhatsApp account ban | High | Use conservative rate limits, no automation of sending, read-only. Consider starting without WhatsApp and adding it last. |
| Telegram ToS for user clients | Medium | Telethon is widely used, don't spam, only read. Low risk for personal use. |
| WhatsApp session drops | Medium | Auto-reconnect logic, notification when session dies. |
| Laptop sleeps/closes | Low | Agent catches up on wake. Not a critical system. |
| API costs (Anthropic) | Low | Use Haiku/Sonnet for routine tasks, Opus only when needed. Medium volume = low cost. |

## Decision Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-03-04 | Run on sister's laptop | WhatsApp needs local presence, avoids cloud costs, better privacy |
| 2025-03-04 | Telegram bot as UI | She already uses Telegram, zero learning curve |
| 2025-03-04 | SQLite + FTS5 | Lightweight, zero-config, great for local search |
| 2025-03-04 | Python | Best library ecosystem for all 3 integrations + Anthropic SDK |
| 2025-03-04 | Claude API as LLM | User preference, strong tool-use support for calendar actions |

## Open Questions
- [ ] WhatsApp library choice — need to research current state of Python WhatsApp libs
- [ ] Does sister want ALL chats synced or only specific contacts/groups?
- [ ] Alert criteria — what counts as "important"? (LLM-classified or rule-based?)
- [ ] How far back should initial message sync go?
