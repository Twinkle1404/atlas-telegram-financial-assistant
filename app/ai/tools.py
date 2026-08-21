"""
Tool definitions for Claude's function-calling loop, plus the dispatcher that
actually executes them. Keeping schema + implementation lookup in one file
makes it hard for them to drift out of sync.

Each tool wraps a `services/` module -- the tool layer is intentionally thin:
its job is argument validation + calling the service + returning compact
JSON-able results, not business logic.
"""
import json
from datetime import datetime, timedelta

from app.services import (
    market_data, news_service, sec_service, memory_service,
    portfolio_service, memo_service, workspace_service, macro_service
)
from app.models.watchlist import WatchlistItem, ScheduledEvent
from app.models.document import Document
from app.database import get_session


TOOL_SCHEMAS = [
    {
        "name": "get_stock_quote",
        "description": "Get the latest price, day change, and basic trading stats for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Stock ticker, e.g. AAPL"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_company_fundamentals",
        "description": "Get company fundamentals: sector, market cap, P/E, revenue, margins, growth, description.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_company_news",
        "description": "Get the most recent notable news headlines for a company or ticker, with source and date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Company name or ticker"},
                "max_items": {"type": "integer", "default": 6},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_sec_filings",
        "description": "Get recent SEC EDGAR filings (10-K, 10-Q, 8-K, Form 4 insider transactions, etc.) for a public company.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "form_type": {"type": "string", "description": "Optional filter, e.g. '8-K', '10-Q', '4'"},
                "max_items": {"type": "integer", "default": 5},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "compare_companies",
        "description": "Get side-by-side fundamentals for 2-4 companies to support an investment comparison.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4}
            },
            "required": ["tickers"],
        },
    },
    {
        "name": "get_market_overview",
        "description": "Get a snapshot of major index performance (S&P 500, Nasdaq, Dow) for today's/yesterday's session.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_to_watchlist",
        "description": "Start proactively monitoring a ticker for the user (news + filings + optional price-move alerts).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "company_name": {"type": "string"},
                "reason": {"type": "string", "description": "Why the user cares, in a few words"},
                "move_pct_threshold": {
                    "type": "number",
                    "description": "Optional: alert if the stock moves more than this % in a day",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "remove_from_watchlist",
        "description": "Stop monitoring a ticker for the user.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "create_reminder",
        "description": "Schedule a one-off reminder/notification to send the user at a specific future time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What to remind them about"},
                "minutes_from_now": {
                    "type": "integer",
                    "description": "When to fire this reminder, in minutes from now",
                },
            },
            "required": ["description", "minutes_from_now"],
        },
    },
    {
        "name": "get_earnings_calendar",
        "description": "Get the next expected earnings date (and EPS estimate if available) for a ticker. Use this for earnings-related reminders or 'when does X report' questions.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_uploaded_document",
        "description": (
            "Retrieve the text/summary of a document the user previously uploaded "
            "(annual report, earnings deck, filing, etc). Use this when the user asks "
            "a follow-up question about 'the document', 'this report', 'that deck', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename_hint": {
                    "type": "string",
                    "description": "Optional partial filename if the user referenced a specific one",
                }
            },
        },
    },
    {
        "name": "update_user_memory",
        "description": (
            "Persist a durable fact learned about the user for future personalization "
            "(role, followed sector, recurring interest, preference, etc). Call this "
            "whenever the user reveals something worth remembering long-term."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "One concise, durable fact, e.g. 'Focuses on semiconductor and AI infrastructure stocks'"},
            },
            "required": ["fact"],
        },
    },
    {
        "name": "analyze_portfolio",
        "description": "Analyze portfolio holdings (e.g. '100 AAPL, 50 NVDA, 200 SPY'), computing total valuation in Indian Rupees (₹), sector concentration, aggregate beta, and automated risk flags.",
        "input_schema": {
            "type": "object",
            "properties": {"holdings": {"type": "string", "description": "Holding details in natural text or ticker list"}},
            "required": ["holdings"],
        },
    },
    {
        "name": "export_research_memo",
        "description": "Synthesize conversation research, metrics, and filings into a formal Investment Committee (IC) One-Pager Markdown document for file download.",
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "Target company name, ticker, or topic"}},
            "required": ["topic"],
        },
    },
    {
        "name": "search_workspace_emails",
        "description": "Search connected Gmail archive for team discussions, earnings notes, client emails, or acquisition notes.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search term or ticker"}},
            "required": ["query"],
        },
    },
    {
        "name": "schedule_calendar_event",
        "description": "Schedule a meeting, IC presentation, or earnings call review event in Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_time": {"type": "string", "description": "e.g. 'Tomorrow 3:00 PM' or ISO datetime"},
                "duration_minutes": {"type": "integer", "default": 30},
                "description": {"type": "string"},
            },
            "required": ["title", "start_time"],
        },
    },
    {
        "name": "analyze_financial_spreadsheet",
        "description": "Parse financial model spreadsheets, Google Sheets, or CSV files to analyze YoY growth, margins, and highlight numerical anomalies.",
        "input_schema": {
            "type": "object",
            "properties": {"file_hint": {"type": "string", "description": "Filename or spreadsheet description"}},
        },
    },
    {
        "name": "search_google_web",
        "description": "Search Google Web/News for real-time news headlines, company updates, or global market events.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query or topic"}},
            "required": ["query"],
        },
    },
    {
        "name": "search_google_drive",
        "description": "Search Google Drive workspace for research decks, investment memos, or due diligence papers.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_macro_indicators",
        "description": "Get key macroeconomic indicators: 10Y Treasury yield, VIX volatility, USD/INR, DXY, Crude Oil.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_economic_calendar",
        "description": "Get upcoming major global macroeconomic calendar events (FOMC, CPI, RBI policy, NFP).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_historical_financials",
        "description": "Get 5-year multi-year P/L historical financial statement data (Revenue, Net Profit, Margins, Turning points).",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_company_health_score",
        "description": "Get a transparent 5-factor AI Research Score (0-10) for a company with score breakdown and justification.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_competitors",
        "description": "Get main industry competitors and rival companies for a stock ticker.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "generate_stock_chart",
        "description": "Generate a visual Matplotlib stock price chart (with 20-day SMA, 50-day SMA, and volume subplots) for a company stock ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker e.g. TATAMOTORS.NS, AAPL, RELIANCE.NS"},
                "period": {"type": "string", "description": "Time period e.g. '1m', '3m', '6m', '1y'", "default": "6m"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "generate_comparison_chart",
        "description": "Generate a comparative Matplotlib percentage return performance chart comparing multiple stocks side-by-side.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of tickers e.g. ['TATAMOTORS.NS', 'M&M.NS'] or ['AAPL', 'MSFT']"
                },
                "period": {"type": "string", "description": "Time period e.g. '1m', '3m', '6m', '1y'", "default": "6m"}
            },
            "required": ["tickers"],
        },
    },
]


def _quote_result(ticker: str) -> dict:
    return market_data.get_quote(ticker)


def _fundamentals_result(ticker: str) -> dict:
    return market_data.get_fundamentals(ticker)


def dispatch_tool(name: str, tool_input: dict, user_id: int) -> str:
    """Executes a tool call and returns a JSON string result for the model."""
    try:
        if name == "get_stock_quote":
            result = _quote_result(tool_input["ticker"])

        elif name == "get_company_fundamentals":
            result = _fundamentals_result(tool_input["ticker"])

        elif name == "get_company_news":
            result = news_service.get_company_news(
                tool_input["query"], tool_input.get("max_items", 6)
            )

        elif name == "get_sec_filings":
            result = sec_service.get_recent_filings(
                tool_input["ticker"],
                tool_input.get("form_type"),
                tool_input.get("max_items", 5),
            )

        elif name == "compare_companies":
            result = {t: _fundamentals_result(t) for t in tool_input["tickers"]}

        elif name == "get_market_overview":
            result = market_data.get_market_overview()

        elif name == "get_earnings_calendar":
            result = market_data.get_earnings_calendar(tool_input["ticker"])

        elif name == "add_to_watchlist":
            result = _add_to_watchlist(user_id, tool_input)

        elif name == "remove_from_watchlist":
            result = _remove_from_watchlist(user_id, tool_input["ticker"])

        elif name == "create_reminder":
            result = _create_reminder(user_id, tool_input)

        elif name == "get_uploaded_document":
            result = _get_uploaded_document(user_id, tool_input.get("filename_hint"))

        elif name == "update_user_memory":
            memory_service.add_learned_fact(user_id, tool_input["fact"])
            result = {"status": "saved"}

        elif name == "analyze_portfolio":
            result = portfolio_service.analyze_portfolio(tool_input["holdings"])

        elif name == "export_research_memo":
            result = memo_service.export_research_memo(user_id, tool_input["topic"])

        elif name == "search_workspace_emails":
            result = workspace_service.search_emails(tool_input["query"])

        elif name == "schedule_calendar_event":
            result = workspace_service.schedule_calendar_event(
                tool_input["title"],
                tool_input["start_time"],
                tool_input.get("duration_minutes", 30),
                description=tool_input.get("description", "")
            )

        elif name == "analyze_financial_spreadsheet":
            result = workspace_service.analyze_spreadsheet(tool_input.get("file_hint", ""))

        elif name == "search_google_web":
            result = news_service.google_web_search(tool_input["query"])

        elif name == "search_google_drive":
            result = workspace_service.search_google_drive(tool_input["query"])

        elif name == "get_macro_indicators":
            result = macro_service.get_macro_indicators()

        elif name == "get_economic_calendar":
            result = macro_service.get_economic_calendar()

        elif name == "get_historical_financials":
            result = market_data.get_historical_financials(tool_input["ticker"])

        elif name == "get_company_health_score":
            result = market_data.calculate_health_score(tool_input["ticker"])

        elif name == "get_competitors":
            result = market_data.get_competitors(tool_input["ticker"])

        elif name == "generate_stock_chart":
            from app.services import chart_service
            chart_path = chart_service.generate_stock_chart(
                tool_input["ticker"], tool_input.get("period", "6m")
            )
            result = {"status": "success", "chart_path": chart_path, "ticker": tool_input["ticker"]}

        elif name == "generate_comparison_chart":
            from app.services import chart_service
            chart_path = chart_service.generate_comparison_chart(
                tool_input["tickers"], tool_input.get("period", "6m")
            )
            result = {"status": "success", "chart_path": chart_path, "tickers": tool_input["tickers"]}

        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as exc:  # tool failures shouldn't crash the conversation
        result = {"error": str(exc)}

    return json.dumps(result, default=str)


def _add_to_watchlist(user_id: int, args: dict) -> dict:
    with get_session() as session:
        existing = (
            session.query(WatchlistItem)
            .filter_by(user_id=user_id, ticker=args["ticker"].upper())
            .first()
        )
        if existing:
            existing.reason = args.get("reason", existing.reason)
            existing.move_pct_threshold = args.get("move_pct_threshold", existing.move_pct_threshold)
            return {"status": "already_watching", "ticker": existing.ticker}

        item = WatchlistItem(
            user_id=user_id,
            ticker=args["ticker"].upper(),
            company_name=args.get("company_name", ""),
            reason=args.get("reason", ""),
            move_pct_threshold=args.get("move_pct_threshold"),
        )
        session.add(item)
        return {"status": "added", "ticker": item.ticker}


def _remove_from_watchlist(user_id: int, ticker: str) -> dict:
    with get_session() as session:
        item = (
            session.query(WatchlistItem)
            .filter_by(user_id=user_id, ticker=ticker.upper())
            .first()
        )
        if item:
            session.delete(item)
            return {"status": "removed", "ticker": ticker.upper()}
        return {"status": "not_found", "ticker": ticker.upper()}


def _get_uploaded_document(user_id: int, filename_hint: str | None) -> dict:
    with get_session() as session:
        query = session.query(Document).filter_by(user_id=user_id)
        if filename_hint:
            query = query.filter(Document.filename.ilike(f"%{filename_hint}%"))
        doc = query.order_by(Document.created_at.desc()).first()
        if not doc:
            return {"error": "No uploaded document found."}
        return {
            "filename": doc.filename,
            "summary": doc.summary,
            "text_excerpt": (doc.extracted_text or "")[:8000],
        }


def _create_reminder(user_id: int, args: dict) -> dict:
    fire_at = datetime.utcnow() + timedelta(minutes=int(args["minutes_from_now"]))
    with get_session() as session:
        event = ScheduledEvent(user_id=user_id, description=args["description"], fire_at_utc=fire_at)
        session.add(event)
    return {"status": "scheduled", "fire_at_utc": fire_at.isoformat()}
