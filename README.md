# Sister AI Agent

Personal AI assistant that reads Gmail, Telegram, and WhatsApp messages, answers questions about message history, and creates Google Calendar events. Controlled via a Telegram bot. Runs locally on sister's laptop.

## Setup

```bash
poetry install
cp .env.example .env  # fill in your secrets
python auth_google.py  # first-time Google OAuth
```

See `PLAN.md` for full architecture and module breakdown.
