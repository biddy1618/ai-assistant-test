# Sister AI Agent — Claude Code Instructions

## Project Overview

A personal AI assistant for my sister. Reads her WhatsApp, Telegram, and Gmail (read-only), creates Google Calendar events (write), and answers questions about her message history. She interacts via a Telegram bot. Runs locally on her laptop.

## Current Task: Google Console API Setup (Module 2 — Gmail Connector)

Setting up Google Cloud project for Gmail (read-only) + Google Calendar (write) access via OAuth2.

### Google Cloud Setup Checklist

- [ ] Create Google Cloud project under her account
- [ ] Enable **Gmail API** (`gmail.googleapis.com`)
- [ ] Enable **Google Calendar API** (`calendar-json.googleapis.com`)
- [ ] Configure **OAuth consent screen**
  - Type: External
  - Mode: Testing
  - Add her email as a test user
  - Scopes: `gmail.readonly`, `calendar.events`
- [ ] Create **OAuth 2.0 Client ID** (type: Desktop app)
- [ ] Download `credentials.json` → place at `config/credentials.json`
- [ ] Run OAuth flow once to generate `config/token.json`
- [ ] Add both files to `.gitignore`

### OAuth2 Flow (how it works)

1. First run: opens browser → user logs in → grants consent → saves `token.json`
2. Subsequent runs: loads `token.json` automatically, refreshes if expired
3. Credentials file: `config/credentials.json` (never commit this)
4. Token file: `config/token.json` (never commit this)

### Gmail Scopes

```
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/calendar.events
```

### Key Files for This Module

```
config/
├── credentials.json      # Downloaded from Google Cloud Console (DO NOT COMMIT)
├── token.json            # Generated after first OAuth flow (DO NOT COMMIT)
└── .env.example          # Template for secrets
src/connectors/
└── gmail_connector.py    # Gmail API connector (Module 2)
src/agent/
└── calendar.py           # Google Calendar write actions (Module 7)
```

## Architecture

```
WhatsApp (Baileys/TBD) ─┐
Telegram (Telethon)     ──► SQLite + FTS5 ──► Claude API ──► Telegram Bot UI
Gmail (google-api)      ─┘                              └──► Google Calendar (write)
```

## Tech Stack

| Component | Library | Notes |
|-----------|---------|-------|
| LLM | `anthropic` | Sonnet for routine, Opus for complex |
| Database | SQLite + FTS5 | `aiosqlite` for async |
| Gmail + Calendar | `google-api-python-client` + `google-auth-oauthlib` | OAuth2 Desktop flow |
| Telegram reader | `telethon` | User client, phone number auth |
| Telegram bot | `python-telegram-bot` | Bot UI her sister uses |
| Config | `.env` + YAML | `python-dotenv` + `pyyaml` |
| Validation | `pydantic` v2 | Data models |
| Logging | `loguru` | Structured logs |

## Build Order

1. **Module 1** ✅ Project setup + SQLite schema + base connector
2. **Module 2** ← CURRENT: Gmail connector (OAuth2 setup in progress)
3. **Module 3** Telegram connector (Telethon)
4. **Module 4** WhatsApp connector (highest risk, do last)
5. **Module 5** Telegram bot interface
6. **Module 6** AI agent core (summarization, Q&A, search, alerts)
7. **Module 7** Google Calendar integration
8. **Module 8** Polish & deployment

## Coding Conventions

- Python 3.11+, async/await throughout (`asyncio`)
- Type hints everywhere
- Docstrings on all public classes and functions
- Linter: `ruff` (line length 100, target py311)
- Tests: `pytest` + `pytest-asyncio`
- Follow PEP 8

## Secrets & Security

**Never commit:**
- `config/credentials.json`
- `config/token.json`
- `.env`
- Any Telegram session files (`*.session`)

**Always use `.env` for:**
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`

## Key Decisions & Constraints

- WhatsApp is **optional and pluggable** — don't make it a hard dependency. It's the riskiest integration (no official API, account ban risk).
- Telegram user client (Telethon) has mild ToS risk. Read-only, no spam.
- Design for **graceful catch-up** after downtime (laptop closes/sleeps).
- Message volume: ~10–50 messages/day across platforms.
- Sync history depth: configurable (not yet decided).
- "Important" alert criteria: start with LLM classification, refine later.

## Commands

```bash
# Install dependencies
poetry install

# Run linter
poetry run ruff check .

# Run tests
poetry run pytest

# Run main app
poetry run python main.py
```
