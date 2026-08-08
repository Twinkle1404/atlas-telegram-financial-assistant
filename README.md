# AI Financial Assistant — Telegram

An AI financial assistant that lives in Telegram and behaves like an analyst
on call, not a chatbot: it remembers who you are, pulls live market data,
reads documents, and only speaks up proactively when something actually
matters.

## Why it's built this way

**One conversational loop, not a feature list.** Every capability — stock
quotes, fundamentals, news, SEC filings, watchlists, reminders, memory
updates, document lookup — is exposed to Claude as a *tool*. The user never
picks a mode; they just talk, and Claude decides which tools (if any) a
given message needs. This is what keeps the product command-free per the
brief: there is exactly one Telegram command (`/start`, unavoidable — it's
how Telegram opens a bot chat), everything else is prose in, prose out.

**Personalization is a living profile, not onboarding answers.** `User.profile_json`
holds role, followed sectors, watchlist context, insight preferences, and a
running list of learned facts. Onboarding (`app/bot/onboarding.py`) seeds it
through a natural conversation (skippable at any point), and the
`update_user_memory` tool lets Claude add to it during *any* later
conversation — so the assistant keeps getting sharper the more you use it,
exactly as the spec asks.

**Proactive, not noisy.** `app/scheduler/jobs.py` runs three background jobs:
daily briefings, watchlist move/filing alerts, and reminders. The briefing
job explicitly asks Claude to reply `NOTHING_NOTABLE` when there's nothing
worth a message, and the code treats that as "send nothing" — quality over
frequency, per the brief.

**Documents and chat share memory.** Uploading a report immediately gets
summarized (not just stored), and a `get_uploaded_document` tool lets any
later question ("what were the biggest risks?") pull the extracted text back
in — so document Q&A feels like a continuation of the conversation, not a
separate mode.

## Architecture

```
run.py                     Boots DB, Telegram polling app, APScheduler jobs
app/
  config.py                Env-driven settings, single source of truth
  database.py               SQLAlchemy engine/session
  models/                   User, Message, WatchlistItem, ScheduledEvent, Document
  ai/
    prompts.py              System prompt built fresh per-turn from live user profile
    tools.py                Tool schemas + dispatcher (the "hands" of the assistant)
    claude_client.py        Tool-use loop, onboarding, document Q&A, image analysis
  services/
    market_data.py          yfinance: quotes, fundamentals, index overview
    news_service.py         NewsAPI (if configured) else yfinance news
    sec_service.py           SEC EDGAR: ticker->CIK->recent filings
    document_service.py     PDF/text extraction
    voice_service.py        Whisper transcription (OpenAI API)
    memory_service.py       Profile read/merge/learn
    conversation_service.py  Chat history log + retrieval
  bot/
    handlers.py              Telegram entrypoints: text/voice/photo/document
    onboarding.py            Natural-language onboarding flow
  scheduler/
    jobs.py                  Daily briefing / watchlist alerts / reminders
  utils/formatting.py        Telegram-safe message trimming/chunking
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN (from @BotFather) and ANTHROPIC_API_KEY at minimum
python run.py
```

Everything else in `.env` is optional and degrades gracefully:
- No `OPENAI_API_KEY` → voice notes get a friendly "not configured yet" reply; text/images still work.
- No `NEWSAPI_KEY` → news falls back to yfinance's built-in feed.
- SEC EDGAR and yfinance need no keys at all.

## Developing without Telegram

`scripts/chat_cli.py` runs the exact same pipeline (memory, tools, onboarding)
straight in your terminal, so you can iterate on prompts/tools without
round-tripping through Telegram for every test:

```bash
python scripts/chat_cli.py
# or: make chat
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
# or: make test
```

Each test runs against a fresh in-memory SQLite DB (`tests/conftest.py`), so
they're isolated and fast. Coverage: personalization/memory merging, watchlist
tool dispatch, formatting/chunking, and SEC EDGAR lookup (HTTP mocked).

## Example conversations it's built to handle

- "What are the biggest market-moving events I should know about today?"
- "Compare Microsoft and Google from an investment perspective."
- "Track Tesla and notify me whenever there's a major announcement or filing."
- "Remind me one hour before Apple's earnings call."
- *(upload a PDF)* → auto-summary, then "what are the biggest risks in here?"
- *(send a chart screenshot)* → "what's going on with this?"
- "Tell me about Apple" → assistant asks whether you want news, financials,
  valuation, or an overview, instead of guessing.
- "When does Apple report earnings next?" → `get_earnings_calendar` tool.

## Known limitations (prototype scope, called out intentionally)

- **Timezones**: `briefing_hour_local` is compared against UTC hour for
  simplicity. A production build would capture each user's IANA timezone and
  convert with `zoneinfo`.
- **Google integrations** (Gmail/Calendar/Drive/Sheets): the config and
  onboarding conversation reference them, and `User.integrations_json` is
  ready to hold OAuth tokens, but the OAuth flow itself isn't wired up here —
  it's the natural next module to add (`app/services/google_service.py` +
  a `/oauth/google/callback` route) without touching the rest of the
  architecture.
- **Single-process scheduling**: APScheduler runs in-process; a multi-instance
  deployment would move this to a durable job queue (Celery/RQ + Redis).
- **Voice** requires an OpenAI key for Whisper; swappable for a local
  faster-whisper model if fully offline transcription is needed.
