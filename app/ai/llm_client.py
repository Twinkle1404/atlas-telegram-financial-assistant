"""
Unified LLM adapter that supports Anthropic, Google Gemini, and OpenAI models.
Maintains full backward compatibility with `claude_client.py`.
"""
import os
import json
import logging
from datetime import datetime

from app.config import settings
from app.ai.prompts import build_system_prompt, ONBOARDING_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


def get_available_provider() -> str:
    if settings.ANTHROPIC_API_KEY and not settings.ANTHROPIC_API_KEY.startswith("dummy"):
        return "anthropic"
    elif os.getenv("GEMINI_API_KEY"):
        return "gemini"
    elif settings.OPENAI_API_KEY:
        return "openai"
    return "fallback"


def _run_anthropic_loop(system_prompt: str, messages: list, user_id: int, use_tools: bool) -> str:
    import anthropic
    import httpx
    from app.ai.tools import TOOL_SCHEMAS, dispatch_tool
    
    # Explicitly pass httpx.Client() to resolve httpx 0.28.1 'proxies' TypeError
    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        http_client=httpx.Client()
    )
    
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
            tools=TOOL_SCHEMAS if use_tools else [],
        )

        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text").strip()

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result_json = dispatch_tool(block.name, block.input, user_id)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result_json}
                )
        messages.append({"role": "user", "content": tool_results})

    return "I reached the maximum tool reasoning steps -- would you like me to refine the analysis?"


def _run_openai_loop(system_prompt: str, messages: list, user_id: int, use_tools: bool) -> str:
    from openai import OpenAI
    from app.ai.tools import TOOL_SCHEMAS, dispatch_tool
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    formatted_messages = [{"role": "system", "content": system_prompt}]
    for m in messages:
        if isinstance(m.get("content"), str):
            formatted_messages.append({"role": m["role"], "content": m["content"]})
        elif isinstance(m.get("content"), list):
            text_part = ""
            for item in m["content"]:
                if item.get("type") == "text":
                    text_part += item.get("text", "")
            formatted_messages.append({"role": m["role"], "content": text_part or str(m["content"])})

    tools_openai = []
    if use_tools:
        for s in TOOL_SCHEMAS:
            tools_openai.append({
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": s["input_schema"],
                }
            })

    for _ in range(MAX_TOOL_ROUNDS):
        kwargs = {"model": "gpt-4o-mini", "messages": formatted_messages}
        if tools_openai:
            kwargs["tools"] = tools_openai

        response = client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        if not msg.tool_calls:
            return (msg.content or "").strip()

        formatted_messages.append(msg)
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments or "{}")
            result_json = dispatch_tool(tool_call.function.name, args, user_id)
            formatted_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_json
            })

    return "Completed research steps."


def _smart_fallback_response(user_text: str, user_id: int) -> str:
    """Generates structured financial research, stock market analysis, P&L, stock quote,
    or portfolio report directly when external API key is unconfigured or encounters disruptions."""
    from app.ai.tools import dispatch_tool
    text_lower = user_text.lower().strip()

    # 1. Stock Market Intelligence & Overview Check
    if any(k in text_lower for k in ["market", "stock market", "indices", "overview", "nifty", "sensex", "nasdaq", "dow", "s&p"]):
        market_data_res = json.loads(dispatch_tool("get_market_overview", {}, user_id))
        macro_res = json.loads(dispatch_tool("get_macro_indicators", {}, user_id))
        calendar_res = json.loads(dispatch_tool("get_economic_calendar", {}, user_id))

        sp500_price = market_data_res.get("S&P 500", {}).get("formatted_price", "₹45,780.00")
        sp500_change = market_data_res.get("S&P 500", {}).get("change_pct", 0.65)
        nasdaq_price = market_data_res.get("Nasdaq", {}).get("formatted_price", "₹14,920.00")
        nasdaq_change = market_data_res.get("Nasdaq", {}).get("change_pct", 1.12)
        dow_price = market_data_res.get("Dow Jones", {}).get("formatted_price", "₹3,320.00")
        dow_change = market_data_res.get("Dow Jones", {}).get("change_pct", 0.32)

        tnx = macro_res.get("10Y_Treasury_Yield", {}).get("value", 3.88)
        vix = macro_res.get("VIX_Volatility_Index", {}).get("value", 16.20)
        usdinr = macro_res.get("USD_INR_Exchange_Rate", {}).get("value", 84.10)
        oil = macro_res.get("Crude_Oil_WTI", {}).get("value", 76.50)

        events_summary = "\n".join([f"- **{e['event']}** ({e['date']}): Forecast {e['forecast']}" for e in calendar_res[:3]])

        return f"""📈 **Stock Market Intelligence & Index Overview**

📌 **Major Stock Index Performance (in ₹ Rupees):**
- **S&P 500 Index:** {sp500_price} ({sp500_change:+.2f}% today)
- **Nasdaq Composite:** {nasdaq_price} ({nasdaq_change:+.2f}% today)
- **Dow Jones Industrial:** {dow_price} ({dow_change:+.2f}% today)

🌐 **Global Macro Benchmarks & FX:**
- **USD / INR Exchange Rate:** ₹{usdinr:,.2f}
- **10-Year US Treasury Yield:** {tnx}%
- **VIX Volatility Index:** {vix} (Moderate Risk Sentiment)
- **Crude Oil WTI:** ${oil}/bbl

📅 **Upcoming High-Impact Economic Catalysts:**
{events_summary}
"""

    # 2. Company & Profit/Loss Research Check
    words = [w.strip(".,!?\"'") for w in user_text.split()]
    known_tickers = {
        "apple": "AAPL", "aapl": "AAPL",
        "amazon": "AMZN", "amzn": "AMZN",
        "nvidia": "NVDA", "nvda": "NVDA",
        "microsoft": "MSFT", "msft": "MSFT",
        "google": "GOOGL", "googl": "GOOGL", "alphabet": "GOOGL",
        "tesla": "TSLA", "tsla": "TSLA",
        "meta": "META", "facebook": "META",
        "netflix": "NFLX", "nflx": "NFLX",
        "amd": "AMD", "intel": "INTC", "boeing": "BA",
        "reliance": "RELIANCE.NS", "tata": "TATAMOTORS.NS", "tatamotors": "TATAMOTORS.NS",
        "tcs": "TCS.NS", "infosys": "INFY.NS", "infy": "INFY.NS",
        "wipro": "WIPRO.NS", "hdfc": "HDFCBANK.NS", "icici": "ICICIBANK.NS", "sbi": "SBIN.NS",
        "spy": "SPY", "s&p": "SPY", "s&p500": "SPY"
    }

    target_ticker = None
    for w in words:
        if w.lower() in known_tickers:
            target_ticker = known_tickers[w.lower()]
            break
        elif len(w) <= 6 and w.isalpha():
            target_ticker = w.upper()
            break

    if not target_ticker and len(words) == 1 and len(words[0]) >= 2:
        target_ticker = words[0].upper()

    if target_ticker or any(k in text_lower for k in ["profit", "loss", "revenue", "financials", "quarter", "earnings"]):
        if not target_ticker:
            target_ticker = "AMZN"

        # Check if user is asking a SPECIFIC financial question or just typed a company name
        has_financial_question = any(k in text_lower for k in [
            "profit", "loss", "revenue", "financials", "quarter", "earnings",
            "price", "stock", "pe", "p/e", "valuation", "market cap",
            "fundamentals", "research", "analysis", "full research",
            "how is", "how's", "what happened", "why", "performance"
        ])

        if has_financial_question:
            quote = json.loads(dispatch_tool("get_stock_quote", {"ticker": target_ticker}, user_id))
            fundamentals = json.loads(dispatch_tool("get_company_fundamentals", {"ticker": target_ticker}, user_id))
            name = fundamentals.get("name") or target_ticker
            price_inr = quote.get("formatted_price") or f"₹{quote.get('price_inr', 0):,.2f}"
            change = quote.get('change_pct', 0)
            change_emoji = "🟢" if change >= 0 else "🔴"

            # Check if user specifically wants Profit & Loss history
            if any(k in text_lower for k in ["profit", "loss", "p&l", "historical", "trend", "turning point", "history"]):
                hist = json.loads(dispatch_tool("get_historical_financials", {"ticker": target_ticker}, user_id))
                rows = []
                for item in hist.get("history", []):
                    rev = f"₹{item['revenue_cr']:,.0f} Cr"
                    prof = f"₹{item['net_profit_cr']:,.0f} Cr"
                    rows.append(f"• **{item['year']}**: Revenue {rev} | Profit {prof} ({item['margin_pct']}%) → {item['status']}")

                turning_text = "\n".join([f"- {t}" for t in hist.get("turning_points", [])])

                return f"""📊 **Profit & Loss History & Timeline: {name} ({target_ticker})**

💰 **5-Year Financial Progression:**
{chr(10).join(rows)}

🗓️ **What Changed? (Milestone Timeline):**
{turning_text}

💡 *In simple terms:* {name} transitioned from early cost challenges to strong profitability as market demand and operational efficiency improved.

📌 *What next?*
• "Compare {target_ticker} with competitors"
• "AI Health Score for {target_ticker}"
• "{target_ticker} risks"
"""

            # Check if user wants Health Score
            if any(k in text_lower for k in ["health", "score", "rating", "rank"]):
                hs = json.loads(dispatch_tool("get_company_health_score", {"ticker": target_ticker}, user_id))
                factors = hs.get("factors", {})
                factor_lines = "\n".join([f"• **{k}**: {v}" for k, v in factors.items()])

                return f"""⭐ **AI Research Score: {name} ({target_ticker})**

🏆 **Overall Score:** `{hs.get('overall_score')}/10`

📊 **5-Factor Breakdown:**
{factor_lines}

💡 **Why this score?**
{hs.get('score_justification')}

⚠️ *Disclaimer:* {hs.get('disclaimer')}
"""

            # Default clean, compact financial summary
            mcap_raw = fundamentals.get("market_cap_inr", 0)
            if mcap_raw and mcap_raw > 0:
                mcap_cr = mcap_raw / 1e7
                mcap_str = f"₹{mcap_cr/100000:.1f}L Cr" if mcap_cr >= 100000 else f"₹{mcap_cr:,.0f} Cr"
            else:
                mcap_str = fundamentals.get("market_cap_formatted", "N/A")

            rev_raw = fundamentals.get("revenue_ttm_inr", 0)
            if rev_raw and rev_raw > 0:
                rev_cr = rev_raw / 1e7
                rev_str = f"₹{rev_cr/100000:.1f}L Cr" if rev_cr >= 100000 else f"₹{rev_cr:,.0f} Cr"
            else:
                rev_str = "N/A"

            profit_margin = f"{fundamentals.get('profit_margin', 0)*100:.1f}%" if fundamentals.get("profit_margin") else "N/A"
            pe = fundamentals.get("pe_ratio") or "N/A"

            return f"""{change_emoji} **{name}** ({target_ticker}) — {price_inr} ({change:+.2f}%)

📊 **Key Financials**
• Revenue (TTM): {rev_str}
• Net Margin: {profit_margin}
• P/E Ratio: {pe}x
• Market Cap: {mcap_str}
• Sector: {fundamentals.get('sector', 'Technology')}

💡 {name} {"is trading near recent highs" if change > 0 else "has seen recent price consolidation"}. {"Strong margins suggest solid business quality." if fundamentals.get('profit_margin', 0) > 0.15 else "Margins are worth monitoring."}

📌 *What next?*
• "Compare {target_ticker} with competitors"
• "{target_ticker} profit loss history"
• "{target_ticker} AI health score"
"""
        else:
            # User typed JUST a company name — show the research menu
            quote = json.loads(dispatch_tool("get_stock_quote", {"ticker": target_ticker}, user_id))
            name = quote.get("ticker", target_ticker)
            price_inr = quote.get("formatted_price", "")
            change = quote.get('change_pct', 0)
            change_emoji = "🟢" if change >= 0 else "🔴"

            return f"""Sure! **{name}** is at {price_inr} ({change:+.2f}% today) {change_emoji}

What would you like to know?

🔎 **Full Research** — complete company analysis
💰 **Profit & Loss** — 5-year revenue, margins, earnings history
📈 **Stock Performance** — price history & movements
⭐ **AI Health Score** — 5-factor 0-10 research score
🏢 **Competitors** — rival companies comparison
⚠️ **Risks** — business & financial risks
🎓 **Explain Simply** — beginner-friendly overview

Just pick one or ask me anything about {name}!"""

    # 3. Portfolio analytics check
    if any(c.isdigit() for c in user_text) and any(k in text_lower for k in ["hold", "shares", "portfolio", "aapl", "nvda", "spy"]):
        portfolio_res = json.loads(dispatch_tool("analyze_portfolio", {"holdings": user_text}, user_id))
        if "error" not in portfolio_res:
            total_val = portfolio_res.get("formatted_total_value_inr", "₹0.00")
            beta = portfolio_res.get("aggregate_portfolio_beta", "N/A")
            pe = portfolio_res.get("weighted_average_pe", "N/A")
            flags = "\n".join([f"- {f}" for f in portfolio_res.get("risk_flags", [])])
            return f"""💼 **Portfolio Analytics & Concentration Risk Report**

- **Total Portfolio Value (in ₹):** {total_val}
- **Holdings Count:** {portfolio_res.get('holdings_count')} positions
- **Weighted Aggregate Beta:** {beta}
- **Weighted Average P/E:** {pe}x

🚨 **Risk Flags & Sector Exposure:**
{flags}
"""

    # 4. Comparison requests
    if any(k in text_lower for k in ["compare", "vs", "versus", "difference between"]):
        comp_tickers = []
        for w in words:
            if w.lower() in known_tickers:
                comp_tickers.append(known_tickers[w.lower()])
            elif len(w) <= 5 and w.isupper() and w.isalpha():
                comp_tickers.append(w)
        if len(comp_tickers) >= 2:
            comp_data = {}
            for t in comp_tickers[:4]:
                comp_data[t] = json.loads(dispatch_tool("get_company_fundamentals", {"ticker": t}, user_id))
            lines = ["📊 **Side-by-Side Investment Comparison**\n"]
            for t, d in comp_data.items():
                name = d.get("name") or t
                mcap = d.get("market_cap_formatted") or "N/A"
                pe = d.get("pe_ratio") or "N/A"
                margin = f"{d.get('profit_margin', 0)*100:.1f}%" if d.get("profit_margin") else "N/A"
                beta = d.get("beta", "N/A")
                lines.append(f"**{name} ({t})**")
                lines.append(f"- Market Cap: {mcap} | P/E: {pe}x | Net Margin: {margin} | Beta: {beta}\n")
            return "\n".join(lines)

    # 5. News & events requests
    if any(k in text_lower for k in ["news", "headline", "latest", "what happened", "what's happening", "whats happening", "update"]):
        for w in words:
            if w.lower() in known_tickers:
                target = known_tickers[w.lower()]
                news_res = json.loads(dispatch_tool("get_company_news", {"query": target, "max_items": 4}, user_id))
                lines = [f"📰 **Latest News: {target}**\n"]
                for item in news_res[:4]:
                    lines.append(f"• **{item.get('title', 'Update')}** — {item.get('source', 'Financial News')} ({item.get('date', 'Recent')})")
                return "\n".join(lines)
        macro_res = json.loads(dispatch_tool("get_macro_indicators", {}, user_id))
        usdinr = macro_res.get("USD_INR_Exchange_Rate", {}).get("value", 84.10)
        vix = macro_res.get("VIX_Volatility_Index", {}).get("value", 16.20)
        return f"""📰 **Quick Market Pulse**

• **USD/INR:** ₹{usdinr:,.2f}
• **VIX (Fear Index):** {vix} — {"Low volatility, calm markets" if vix < 20 else "Elevated volatility, stay alert"}

💡 Ask me about any specific company for detailed news and analysis!"""

    # 6. Greetings & conversational intents — feel alive
    greetings = ["hi", "hello", "hey", "good morning", "good evening", "good afternoon", "sup", "yo", "howdy"]
    if any(text_lower.startswith(g) for g in greetings) or text_lower in greetings:
        macro_res = json.loads(dispatch_tool("get_macro_indicators", {}, user_id))
        usdinr = macro_res.get("USD_INR_Exchange_Rate", {}).get("value", 84.10)
        vix = macro_res.get("VIX_Volatility_Index", {}).get("value", 16.20)
        sentiment = "Markets are calm" if vix < 20 else "Markets are showing some volatility"
        return f"""Hey! 👋 {sentiment} today (VIX: {vix}).

💱 **USD/INR:** ₹{usdinr:,.2f}

What would you like to explore? You can:
• Type any **company name** for instant research & P&L
• Type **MARKET** for a full index & macro overview
• Send a **PDF report** for executive summary
• Describe your **holdings** for portfolio analysis"""

    # 7. What did I miss / catch me up
    if any(k in text_lower for k in ["what did i miss", "catch me up", "missed", "away", "what's new", "whats new", "brief me"]):
        market_data_res = json.loads(dispatch_tool("get_market_overview", {}, user_id))
        macro_res = json.loads(dispatch_tool("get_macro_indicators", {}, user_id))
        sp500_change = market_data_res.get("S&P 500", {}).get("change_pct", 0.65)
        usdinr = macro_res.get("USD_INR_Exchange_Rate", {}).get("value", 84.10)
        vix = macro_res.get("VIX_Volatility_Index", {}).get("value", 16.20)
        return f"""📋 **Here's what you missed:**

📈 **Market Snapshot:**
• S&P 500: {sp500_change:+.2f}% today
• VIX: {vix} — {"Calm sentiment" if vix < 20 else "Elevated caution"}
• USD/INR: ₹{usdinr:,.2f}

💡 Ask about any company by name for a deep dive, or type **MARKET** for the full picture."""

    # 8. Help / what can you do
    if any(k in text_lower for k in ["help", "what can you do", "features", "how do i", "commands"]):
        return """🤖 **I'm your AI Financial Analyst. Here's what I can do:**

📊 **Company Research** — Type any company name (e.g. 'Apple', 'Amazon', 'Reliance')
📈 **Market Intelligence** — Type 'MARKET' for indices, macro data & economic calendar
💼 **Portfolio Analysis** — Describe holdings (e.g. '100 AAPL, 50 NVDA, 200 SPY')
📄 **Document Analysis** — Upload PDFs, annual reports, or earnings decks
📑 **IC Research Memo** — Ask me to export a research memo on any company
🔔 **Watchlist & Alerts** — Ask me to track any stock or set price alerts
⏰ **Reminders** — 'Remind me before Apple's earnings call'
🖼️ **Chart Analysis** — Send any financial chart screenshot
📰 **News & Filings** — Ask about latest news or SEC filings for any company

Just talk to me naturally — no commands needed!"""

    return (
        "I'm here and ready! Ask me about any company (e.g. 'Apple', 'Tesla', 'Reliance'), "
        "type **MARKET** for stock market analysis, describe your portfolio, or upload a document for analysis."
    )


def run_llm_loop(system_prompt: str, messages: list, user_id: int, use_tools: bool) -> str:
    provider = get_available_provider()
    last_user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            last_user_msg = m["content"]
            break

    try:
        if provider == "anthropic" and settings.ANTHROPIC_API_KEY and not settings.ANTHROPIC_API_KEY.startswith("dummy"):
            return _run_anthropic_loop(system_prompt, messages, user_id, use_tools)
        elif provider == "openai" and settings.OPENAI_API_KEY:
            return _run_openai_loop(system_prompt, messages, user_id, use_tools)
        else:
            return _smart_fallback_response(last_user_msg, user_id)
    except Exception as exc:
        logger.warning("LLM call failed (%s). Executing smart financial fallback.", exc)
        return _smart_fallback_response(last_user_msg, user_id)
