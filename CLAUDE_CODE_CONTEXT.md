# Sister AI Agent — Context for Claude Code

You are helping me build a personal AI assistant for my sister. Here is everything we've decided so far. Treat this as the ground truth for the project.

## What It Does
A read-only AI agent that connects to my sister's personal WhatsApp, Telegram, and Gmail — plus write access to Google Calendar. She interacts with the agent by messaging a Telegram bot. It runs locally on her laptop.

## Core Features
1. **Summarize unread messages** across all platforms
2. **Answer questions** about message history ("what did Mom say on WhatsApp yesterday?")
3. **Search/find specific conversations** across platforms
4. **Alert on important messages** (criteria TBD — likely LLM-classified)
5. **Create calendar events** extracted from messages (with confirmation before creating)

## Architecture Decisions (Finalized)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.11+ | Best library ecosystem for all integrations |
| LLM | Anthropic API (Claude) | My preference. Use Sonnet for routine, Opus for complex |
| Database | SQLite + FTS5 | Lightweight, zero-config, great full-text search |
| UI | Telegram bot (python-telegram-bot) | She already uses Telegram, zero learning curve |
| Hosting | Sister's laptop (local) | WhatsApp needs local presence, no cloud costs, better privacy |
| Dependency mgmt | Poetry | My preference |
| WhatsApp | whatsapp-web.js / Baileys (TBD) | No official API for personal accounts. Reverse-engineered protocol. Risk of session drops and potential account restrictions from Meta |
| Telegram reader | Telethon (user client) | Reads her personal messages. Requires phone number auth with her account |
| Telegram bot | python-telegram-bot | Separate bot she messages to interact with the agent |
| Gmail | google-api-python-client, gmail.readonly scope | Official API, free within quota |
| Calendar | google-api-python-client, calendar.events scope | Official API, free within quota |
| Config | .env for secrets, YAML for preferences | Standard approach |

## Key Context
- Sister has a personal Gmail (Google Workspace). I'm setting up a Google Cloud project under her account for Gmail + Calendar API access. She has $300 GCP free credits but the APIs we need are free anyway.
- Google Cloud setup in progress: need to create project, enable Gmail + Calendar APIs, configure OAuth consent screen (external, test mode, her email as test user), create OAuth 2.0 Desktop Client ID, download credentials.json.
- Message volume is medium: 10-50 messages/day across platforms.
- Sync scope and history depth are not yet decided — implement with configurability in mind.
- WhatsApp library choice is not finalized — needs research into current state of Python-compatible WhatsApp libs (Baileys, whatsapp-web.js with Python bridge, etc.).
- "Important message" alert criteria not yet defined — start with LLM classification, refine later.

## Risks to Keep in Mind
- **WhatsApp is the riskiest integration.** No official personal API. Unofficial libs break. Accounts can get banned. Build the system so WhatsApp is optional/pluggable — don't make it a hard dependency.
- **Telegram user client (Telethon)** has mild ToS risk but is widely used for personal automation. Don't spam, only read.
- **Laptop availability** — agent only works when laptop is on. Design for graceful catch-up after downtime.

## Project Structure
```
sister-ai-agent/
├── docs/
│   └── PLAN.md
├── src/
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract connector interface
│   │   ├── gmail_connector.py
│   │   ├── telegram_connector.py
│   │   └── whatsapp_connector.py
│   ├── store/
│   │   ├── __init__.py
│   │   ├── database.py          # SQLite + FTS5 setup
│   │   └── models.py            # Data models
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── core.py              # Main agent orchestrator
│   │   ├── prompts.py           # System prompts & templates
│   │   └── calendar.py          # Google Calendar actions
│   └── bot/
│       ├── __init__.py
│       └── handlers.py          # Telegram bot command & message handlers
├── config/
│   ├── .env.example
│   └── settings.yaml
├── tests/
├── pyproject.toml
├── main.py
└── README.md
```

## Build Order (Modules)
1. **Module 1: Project setup + SQLite schema + base connector interface** ← START HERE
2. **Module 2: Gmail connector**
3. **Module 3: Telegram connector (Telethon user client)**
4. **Module 4: WhatsApp connector** (highest risk, do last among connectors)
5. **Module 5: Telegram bot interface**
6. **Module 6: AI agent core** (summarization, Q&A, search, alerts)
7. **Module 7: Google Calendar integration**
8. **Module 8: Polish & deployment** (auto-start, error handling, logging)

## How to Work With Me
- Build iteratively. Don't implement everything at once.
- After each module, we test it before moving on.
- Ask me questions when you need decisions — don't assume.
- Keep the codebase clean, typed, and well-documented. My sister won't touch the code but I'll maintain it.
