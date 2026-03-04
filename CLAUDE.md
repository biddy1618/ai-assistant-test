# Sister AI Agent — Claude Code Instructions

## Current Task
**Module 3: Telegram Connector** (Telethon user client)

## Context Maintenance
After any milestone, gotcha, or architectural decision — update `MEMORY.md`.
Only update `CLAUDE.md` when the current task changes or a new behavioral rule is needed.

## Subagent Rules
- **Git commit/push** → delegate to subagent
- **Running tests** → delegate to subagent (`poetry run pytest`)
- **Building a new module** → delegate to subagent with `BaseConnector` interface + module spec
- **Debugging isolated errors** → delegate to subagent

## Coding Conventions
- Python 3.11+, `async`/`await` throughout
- Type hints everywhere, docstrings on all public classes/functions
- **Dependency management: `poetry` only** — never `pip install` directly
- Linter: `ruff` (line length 100) — run before committing
- Tests: `pytest` + `pytest-asyncio`

## Security — Never Commit
`config/credentials.json`, `config/token.json`, `.env`, `*.session`

## Commands
```bash
poetry install          # install deps
poetry run ruff check . # lint
poetry run pytest       # test
source .env && git push $GITHUB_REMOTE main  # push
```
