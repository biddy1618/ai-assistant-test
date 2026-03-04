# Sister AI Agent — Claude Code Instructions

## Project Overview

A personal AI assistant for my sister. Reads her WhatsApp, Telegram, and Gmail (read-only), creates Google Calendar events (write), and answers questions about her message history. She interacts via a Telegram bot. Runs locally on her laptop.

## Current Task: Module 3 — Telegram Connector

## Subagent Rules

Delegate the following tasks to subagents to keep the main context clean:

- **Git operations** (commit, push): spawn a subagent with the list of files and commit message
- **Running tests**: spawn a subagent to run `poetry run pytest` and report results
- **Building a new module**: spawn a subagent with the module spec and `BaseConnector` interface
- **Debugging an isolated error**: spawn a subagent with the error and relevant file context

## Google OAuth2 Setup (completed)

- Google Cloud project: `ai-project-489210`
- Client ID: `14129791863-ajdr6dmegfg07u0o01mijumuq0mk883s.apps.googleusercontent.com`
- Scopes: `gmail.readonly`, `calendar.events`
- Auth type: OAuth2 Desktop app (classic token, NOT fine-grained)
- `config/credentials.json` — from Google Cloud Console (gitignored)
- `config/token.json` — generated on sister's Windows laptop (gitignored)
- Sister's email: `a.bota88@gmail.com` (must be added as test user in OAuth consent screen)

### Known OAuth Gotchas

1. **Must add sister's email as test user** in Google Cloud Console → APIs & Services → OAuth consent screen → Test users. Otherwise get `Error 403: access_denied`.
2. **Use classic token** for GitHub, not fine-grained — fine-grained gives 403 unless repo is explicitly selected.
3. **`calendars.get` needs broader scope** than `calendar.events`. Use `events.list` to test Calendar connectivity.
4. **Don't press Ctrl+C** after browser opens for OAuth — wait for the terminal to complete.

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
