# Sister AI Agent — Persistent Memory

> Auto-memory lives here (project root) — not in the container's `/home/agent/.claude/` which is ephemeral.

## Build Progress
- Module 1 ✅ SQLite + FTS5 store, base connector interface
- Module 2 ✅ Gmail connector (183 emails synced, `requests`-based transport for proxy)
- Module 3 ✅ Telegram connector (`src/connectors/telegram_connector.py`) — written, 46 tests passing
- Module 4 ⏳ WhatsApp connector — skipped for now (highest risk, no official API)
- Module 5 ✅ Telegram bot (`src/bot/handlers.py`) — SisterBot class, /start, /sync, auth guard, hourly background sync
- Module 6 ✅ AI agent core (`src/agent/core.py`, `src/agent/prompts.py`) — AgentCore class, FTS5+recent context retrieval, Claude API via asyncio.to_thread
- Module 7 ✅ Google Calendar (`src/agent/calendar.py`) — CalendarManager, event extraction via Claude, proactive suggestion + yes/no confirmation flow in bot
- Module 8 ✅ Wiring (`main.py`, `auth_telegram.py`, updated `setup_and_auth.bat`) — full startup sequence, graceful shutdown, --full-sync flag

## Tech Stack
| Component | Library |
|-----------|---------|
| LLM | `anthropic` (Sonnet routine, Opus complex) |
| Database | SQLite + FTS5 via `aiosqlite` |
| Gmail + Calendar | `google-api-python-client` + `google-auth-oauthlib` + `requests` transport |
| Telegram reader | `telethon` (user client) |
| Telegram bot | `python-telegram-bot` |
| Config | `.env` + YAML |
| Validation | `pydantic` v2 |
| Logging | `loguru` |

## Google OAuth2
- Cloud project: `ai-project-489210`
- Client ID: `14129791863-ajdr6dmegfg07u0o01mijumuq0mk883s.apps.googleusercontent.com`
- Scopes: `gmail.readonly`, `calendar.events`
- Type: OAuth2 Desktop app — classic token (not fine-grained)
- `config/credentials.json` + `config/token.json` — gitignored, live on sister's laptop

### OAuth Gotchas
1. Add sister's email as **test user** in OAuth consent screen or get `403: access_denied`
2. Use **classic** GitHub token — fine-grained tokens give 403 without explicit repo selection
3. `calendars.get` needs broader scope than `calendar.events` — use `events.list` to test
4. Don't press Ctrl+C while browser OAuth flow is running

## Container / Network
- All outbound traffic via proxy: `host.docker.internal:3128`
- `curl` works fine; `httplib2` does NOT respect proxy → `ConnectionRefusedError`
- Fix: use `google.auth.transport.requests.AuthorizedSession` (requests-based)
- See `docs/container-network-issue.md` for full details

## GitHub
- Repo: https://github.com/biddy1618/ai-assistant-test (public)
- Git user: `biddy` / `biddy.as.diddy@gmail.com`
- Token in `.env`: `GITHUB_TOKEN`
- Push: `source .env && git push $GITHUB_REMOTE main`

## Key Constraints
- WhatsApp is optional/pluggable — highest risk (no official API, ban risk)
- Telethon — read-only, no spam, mild ToS risk
- Design for graceful catch-up after laptop sleep/close
- Message volume: ~10–50/day across platforms
