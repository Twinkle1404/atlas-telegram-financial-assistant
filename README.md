# Atlas — AI Financial Assistant for Telegram

An AI-powered Financial Assistant that lives inside Telegram and behaves like an experienced analyst on call — not a chatbot. It remembers who you are, pulls live market data, reads documents, analyzes portfolios, and only speaks up proactively when something actually matters.

**Live Bot**: [t.me/MyAtlas_Finance_AI_Bot](https://t.me/MyAtlas_Finance_AI_Bot)

---

## Design Philosophy

**One conversational loop, not a feature list.** Every capability — stock quotes, fundamentals, news, SEC filings, watchlists, reminders, portfolio analysis, macro indicators, research memos, document Q&A — is exposed to the AI as a *tool*. The user never picks a mode; they just talk naturally, and the AI decides which tools a given message needs. There are no slash commands (except `/start`, which Telegram requires). Everything is prose in, prose out.

**Personalization is a living profile, not onboarding answers.** `User.profile_json` holds role, followed sectors, watchlist context, insight preferences, and up to 40 learned facts. Onboarding seeds it through natural conversation (skippable at any time), and the `update_user_memory` tool lets the AI add to it during *any* later conversation — so the assistant keeps getting sharper the more you use it.

**Proactive, not noisy.** Background jobs deliver morning briefings, evening summaries, watchlist price-move alerts, and scheduled reminders. The briefing job explicitly asks the AI to reply `NOTHING_NOTABLE` when there's nothing worth sending — quality over frequency.

**All monetary values in Indian Rupees (₹).** Live USD/INR exchange rate conversion is applied to all stock quotes, fundamentals, portfolio valuations, and financial reports.

---

## Core Capabilities

### 📊 Company Research & P&L Analysis
Type any company name (e.g. `apple`, `amazon`, `tesla`, `reliance`) to receive an instant bulleted research breakdown:
- Stock Quote & 52-Week Range (in ₹)
- Profit & Loss: TTM Revenue, Gross/Net Margins
- Valuation: Market Cap (₹ Cr), P/E Ratio, Forward P/E
- Analyst Consensus & Target Price

### 📈 Stock Market Intelligence
Type `MARKET` for a full market overview:
- Major Index Performance: S&P 500, Nasdaq, Dow Jones (in ₹)
- Global Macro Benchmarks: USD/INR, 10-Yr Treasury Yield, VIX, WTI Crude Oil
- Upcoming Economic Catalysts: FOMC, CPI, NFP, RBI decisions

### 💼 Portfolio-Level Analysis
Describe holdings naturally (e.g. *"I hold 100 AAPL, 50 NVDA, 200 SPY"*) and receive:
- Total portfolio valuation in ₹
- Sector concentration weights
- Aggregate portfolio beta
- Weighted average P/E
- Automated risk flags

### 📄 IC Research Memo Export
Generate downloadable Investment Committee One-Pager Markdown documents summarizing research, key metrics, thesis points, and risks — sent as files directly in Telegram.

### 📑 Document & Report Analysis
Upload PDFs, annual reports, earnings decks, or financial statements. The assistant:
- Auto-generates 4-6 bullet executive summaries
- Answers follow-up questions from the document
- Highlights risk factors and performance figures in ₹

### 🖼️ Chart & Image Vision
Send screenshots of financial charts or tables for instant AI-powered interpretation.

### 🔔 Proactive Intelligence
- ☀️ **Morning Market Brief**: Personalized daily briefing explaining *why* events matter
- 🌙 **Evening Market Summary**: End-of-day index movements and close drivers
- ⚡ **Watchlist Alerts**: Automatic notifications when tracked stocks exceed movement thresholds
- ⏰ **Scheduled Reminders**: Earnings call reminders, meeting prep, custom alerts

### 🧠 Progressive Learning
The assistant silently remembers user preferences, interests, and patterns across conversations:
- Companies followed, sectors of interest, research patterns
- Reading preferences, briefing schedules, job role context
- Up to 40 durable learned facts per user, with 15 most recent surfaced per turn

---

## Architecture

```
run.py                          Boots DB, Telegram polling, APScheduler jobs
app/
  config.py                     Env-driven settings (single source of truth)
  database.py                   SQLAlchemy engine + session management
  models/
    user.py                     User model with profile_json, integrations_json
    message.py                  Conversation message log
    watchlist.py                WatchlistItem + ScheduledEvent models
    document.py                 Uploaded document storage
  ai/
    prompts.py                  System prompt rebuilt per-turn from live user profile
    tools.py                    17 tool schemas + unified dispatcher
    claude_client.py            Tool-use loop, onboarding, document Q&A, image analysis
    llm_client.py               Multi-provider adapter (Anthropic/OpenAI) + smart fallback
  services/
    market_data.py              Yahoo Finance: quotes, fundamentals, index overview, USD/INR
    news_service.py             NewsAPI (if configured) else yfinance news feed
    sec_service.py              SEC EDGAR: ticker→CIK→recent filings (10-K, 10-Q, 8-K)
    portfolio_service.py        Holdings parser, valuation, beta, sector weights, risk flags
    memo_service.py             IC Research Memo markdown generator & file exporter
    macro_service.py            Macro indicators (TNX, VIX, DXY, Oil) + economic calendar
    workspace_service.py        Gmail, Calendar, Drive, Sheets integration layer
    document_service.py         PDF/text extraction
    voice_service.py            Whisper transcription (OpenAI API)
    memory_service.py           Profile read/merge/learn (progressive personalization)
    conversation_service.py     Chat history log + retrieval
  bot/
    handlers.py                 Telegram entrypoints: text, voice, photo, document
    onboarding.py               Natural conversational onboarding flow
  scheduler/
    jobs.py                     Daily briefings, evening summaries, watchlist alerts, reminders
  utils/
    formatting.py               Telegram-safe message trimming & chunking
tests/
  conftest.py                   Fresh in-memory SQLite DB per test
  test_formatting.py            Message trimming & chunking
  test_memory_service.py        Profile merge, learned facts, onboarding stage
  test_portfolio_service.py     Holdings parsing, portfolio analytics
  test_memo_service.py          IC research memo generation
  test_workspace_service.py     Gmail, Calendar, Drive, Sheets
  test_macro_service.py         Macro indicators & economic calendar
  test_sec_service.py           SEC EDGAR filing lookup (HTTP mocked)
  test_tools_watchlist.py       Watchlist, reminders, memory tool dispatch
scripts/
  chat_cli.py                   Terminal-based development interface
  demo_run.py                   End-to-end demonstration runner
```

---

## Financial Data Sources & Integrations

| Integration | Purpose | Justification |
|---|---|---|
| **Yahoo Finance API** | Real-time stock quotes, fundamentals, earnings calendar, market indices | Primary source for live market data — free, reliable, comprehensive |
| **SEC EDGAR** | Official 10-K, 10-Q, 8-K filings, insider transactions | Authoritative source for regulatory filings — no API key required |
| **USD/INR Exchange Rate** | Live currency conversion (USDINR=X) | Required for Indian Rupee formatting of all monetary values |
| **Gmail** | Email search, conversation summarization, action item extraction | Helps professionals prepare for meetings without switching apps |
| **Google Calendar** | Meeting scheduling, earnings call reminders | Reduces context-switching for time-sensitive financial events |
| **Google Drive** | Document search across research decks and memos | Centralizes access to scattered financial documents |
| **Google Sheets** | Spreadsheet analysis, KPI review, anomaly detection | Enables conversational analysis of financial models |

---

## Engineering Practices

| Practice | Implementation |
|---|---|
| **Telegram Bot Development** | python-telegram-bot v21.x with async handlers for text, voice, photo, document |
| **Natural Conversational AI** | Tool-use loop with 17 registered tools; no slash commands or menus |
| **Multi-Provider LLM Adapter** | Supports Anthropic Claude, OpenAI, with automatic smart fallback |
| **Database Integration** | SQLAlchemy ORM with SQLite (swappable to PostgreSQL); models for Users, Messages, Watchlists, Documents, Events |
| **Background Jobs** | APScheduler with 4 recurring jobs: daily briefings, evening summaries, watchlist alerts, reminders |
| **Clean Project Structure** | Modular `app/` with `ai/`, `bot/`, `models/`, `services/`, `scheduler/`, `utils/` packages |
| **Reusable Components** | Shared formatting utilities, unified tool dispatcher, service layer pattern |
| **Automated Testing** | 26 tests across 8 test files; fresh in-memory DB per test; pytest with mock |
| **Git Version Control** | Hosted on GitHub with incremental, descriptive commits |
| **Environment Configuration** | `.env`-driven settings with `.env.example`; graceful degradation when optional keys are missing |

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN (from @BotFather) at minimum
python run.py
```

Everything else in `.env` is optional and degrades gracefully:
- No `ANTHROPIC_API_KEY` → smart fallback generates structured financial reports directly
- No `OPENAI_API_KEY` → voice notes get a friendly "not configured yet" reply
- No `NEWSAPI_KEY` → news falls back to yfinance's built-in feed
- SEC EDGAR and yfinance need no API keys

## Development

```bash
# Run tests
pip install -r requirements-dev.txt
pytest

# Terminal-based dev interface (no Telegram needed)
python scripts/chat_cli.py

# Or use Makefile shortcuts
make test
make chat
```

## Tests

```bash
pytest
# 26 passed, covering:
# - Message formatting & chunking
# - Memory service: profile merge, learned facts, onboarding
# - Portfolio analysis: holdings parsing, risk flags
# - IC Research Memo generation
# - Workspace services: Gmail, Calendar, Drive, Sheets
# - Macro indicators & economic calendar
# - SEC EDGAR filing lookup (HTTP mocked)
# - Tool dispatch: watchlist, reminders, memory updates
```

---

## Known Limitations (Prototype Scope)

- **Timezones**: `briefing_hour_local` compared against UTC; production would use `zoneinfo`
- **Google OAuth**: Config and service layer are ready; OAuth callback flow is the natural next module
- **Single-process scheduling**: APScheduler runs in-process; production would use Celery/RQ + Redis
- **Voice**: Requires OpenAI API key for Whisper; swappable for local faster-whisper
