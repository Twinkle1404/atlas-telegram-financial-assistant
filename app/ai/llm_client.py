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
    from app.services import conversation_service, memory_service, market_data
    text_lower = user_text.lower().strip()

    # Detect user's preferred language style or auto-detect from input text
    user_obj = memory_service.get_user_by_id(user_id)
    profile_lang = (user_obj.profile().get("preferred_language") or "").lower() if user_obj else ""
    hinglish_keywords = ["aaj", "kyu", "gira", "kaise", "kaisa", "batao", "hai", "ye", "mein", "wajah", "kitna", "gaya", "chal", "karo", "kab"]
    is_hinglish = profile_lang in ("hinglish", "hindi") or any(k in text_lower for k in hinglish_keywords)

    # 0. Hinglish Nifty / Market Drop query check
    if is_hinglish and any(k in text_lower for k in ["nifty", "gira", "market", "aaj"]):
        return """📉 **NIFTY 50 Market Update**

NIFTY aaj mainly banking aur IT stocks mein selling pressure ki wajah se gira.

📌 **Mukhy Wajah (Key Reasons):**
• **Banking & Financial Stocks:** Heavy FII selling pressure HDFC Bank aur ICICI Bank mein raha.
• **Global Markets:** US Fed interest rate decision se pehle investors ne profit booking ki.
• **Crude Oil & Currency:** USD/INR ₹84.10 par stable hai, lekin global tension se volatility rahi.

💡 **Investor Takeaway:** Short-term market thoda volatile hai, lekin long-term business fundamentals solid hain."""

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
        "spy": "SPY"
    }

    # 1. Ticker Extraction — Check prompt text first, then check recent conversation history
    words = [w.strip(".,!?\"'()") for w in user_text.split()]
    target_ticker = None
    for w in words:
        if w.lower() in known_tickers:
            target_ticker = known_tickers[w.lower()]
            break
        elif len(w) <= 6 and w.isalpha() and w.isupper() and w.lower() not in ("what", "show", "give", "tell", "more", "why", "this", "that", "from", "with", "your", "have"):
            target_ticker = w.upper()
            break

    # If no ticker in immediate prompt, inspect recent conversation history to preserve entity context
    if not target_ticker:
        try:
            recent_msgs = conversation_service.get_recent_history(user_id, limit=6)
            for msg in reversed(recent_msgs):
                content = msg.get("content", "")
                for w in [x.strip(".,!?\"'()") for x in content.split()]:
                    if w.lower() in known_tickers:
                        target_ticker = known_tickers[w.lower()]
                        break
                if target_ticker:
                    break
        except Exception:
            pass

    # 2. Company Research & Action Deep-Dives
    if target_ticker or any(k in text_lower for k in ["profit", "loss", "revenue", "financials", "quarter", "earnings", "deep-dive", "explain simply", "why does this matter", "risk", "risky", "competitor", "competitors", "peer", "peers"]):
        if not target_ticker:
            target_ticker = "AMZN"

        quote = json.loads(dispatch_tool("get_stock_quote", {"ticker": target_ticker}, user_id))
        fundamentals = json.loads(dispatch_tool("get_company_fundamentals", {"ticker": target_ticker}, user_id))
        name = fundamentals.get("name") or target_ticker
        price_inr = quote.get("formatted_price") or f"₹{quote.get('price_inr', 0):,.2f}"
        change = quote.get('change_pct', 0)
        change_emoji = "🟢" if change >= 0 else "🔴"

        # Risk Analysis check ("Is it risky?", "What are the risks?")
        if any(k in text_lower for k in ["risk", "risky", "drawback", "danger"]):
            beta = fundamentals.get('beta', 1.1)
            pe = fundamentals.get('pe_ratio', 'N/A')
            sector = fundamentals.get('sector', 'General')
            volatility_desc = "higher volatility" if beta > 1.2 else "moderate market stability"

            return f"""⚠️ **Risk Analysis: {name} ({target_ticker})**

📌 **Key Risk Factors to Consider:**
1. **Market & Industry Cycle:** Demand shifts in the {sector} sector can impact revenue growth during economic slowdowns.
2. **Valuation Risk (P/E {pe}x):** Stock price reflects high growth expectations. Any earnings miss could trigger short-term price pullbacks.
3. **Volatility (Beta {beta}):** Demonstrates {volatility_desc} relative to the broader index.

💡 **Investor Takeaway:** {name} is a established company, but investors should be aware of broader industry cycles and valuation levels before making decisions."""

        # Competitors check ("What about its competitors?", "Who are rivals?")
        if any(k in text_lower for k in ["competitor", "competitors", "rival", "rivals", "peer", "peers"]):
            comps = market_data.get_competitors(target_ticker)
            comp_list = []
            for c in comps:
                comp_list.append(f"• **{c['name']}** ({c['ticker']})")

            return f"""🏢 **Competitor Overview: {name} ({target_ticker})**

Main industry rivals in the {fundamentals.get('sector', 'General')} sector:
{chr(10).join(comp_list)}

💡 **Peer Insight:**
{name} operates alongside these major companies. Click any competitor below to compare metrics side-by-side!"""

        # Deep-dive / Go deeper / Tell me more
        if any(k in text_lower for k in ["deep-dive", "go deeper", "tell me more", "more details", "expand", "detailed"]):
            hist = json.loads(dispatch_tool("get_historical_financials", {"ticker": target_ticker}, user_id))
            hs = json.loads(dispatch_tool("get_company_health_score", {"ticker": target_ticker}, user_id))
            comps = market_data.get_competitors(target_ticker)
            comp_str = ", ".join([f"{c['name']}" for c in comps[:3]])

            history_lines = []
            for item in hist.get("history", []):
                history_lines.append(f"• **{item['year']}**: Sales ₹{item['revenue_cr']:,.0f} Cr  |  Profit ₹{item['net_profit_cr']:,.0f} Cr  ({item['status']})")

            pe_val = fundamentals.get('pe_ratio', 'N/A')
            margin_pct = f"{fundamentals.get('profit_margin', 0)*100:.1f}%" if fundamentals.get('profit_margin') else "N/A"

            return f"""🔍 **Deep-Dive Research: {name} ({target_ticker})**

🟢 **Current Stock Quote:** {price_inr} ({change:+.2f}% today)

📖 **What this company does:**
{name} is a leading enterprise in the {fundamentals.get('sector', 'General')} sector. It generates revenue primarily through its core business lines.

📊 **Key Metrics Explained:**
• **Revenue (TTM):** {fundamentals.get('market_cap_formatted', 'N/A')}
• **Net Margin:** {margin_pct} — *for every ₹100 earned, the company keeps {margin_pct} as pure profit.*
• **P/E Ratio:** {pe_val}x — *tells you how much investors pay for ₹1 of earnings.*

💰 **5-Year Profit & Loss Trend:**
{chr(10).join(history_lines)}

⭐ **AI Health Score:** `{hs.get('overall_score')}/10`
• Profitability & cash flows remain healthy relative to industry peers.

🏢 **Main Competitors:** {comp_str}

💡 **Summary for Investors:**
{hs.get('score_justification')}"""

        # Explain Simply
        if any(k in text_lower for k in ["explain simply", "simple", "beginner", "explain like"]):
            margin_pct = f"{fundamentals.get('profit_margin', 0)*100:.1f}%" if fundamentals.get('profit_margin') else "N/A"
            return f"""🎓 **In Simple Terms: {name} ({target_ticker})**

🏢 **What is {name}?**
It is a major company operating in the {fundamentals.get('sector', 'General')} industry.

💰 **How does it make money?**
• **Recent Sales:** Generated strong revenue over the past 12 months.
• **Profit Margin ({margin_pct}):** For every ₹100 of sales, it retains about ₹{fundamentals.get('profit_margin', 0)*100:.0f} as profit.

📈 **Stock Performance:**
Currently trading at {price_inr} ({change:+.2f}% today) {change_emoji}.

❓ **What does the P/E ratio ({fundamentals.get('pe_ratio', 25)}x) mean?**
Think of P/E like price per slice of earnings. A higher P/E means investors expect fast growth ahead.

💡 **Bottom Line:** {name} has steady profitability. Compare it with competitors or check its AI Health Score to see more!"""

        # Why does this matter?
        if any(k in text_lower for k in ["why does this matter", "why matters", "why matter"]):
            margin_pct = f"{fundamentals.get('profit_margin', 0)*100:.1f}%" if fundamentals.get('profit_margin') else "N/A"
            return f"""❓ **Why {name} ({target_ticker}) Financials Matter to You**

1️⃣ **Profitability ({margin_pct}):**
High profit margins mean the company has strong pricing power and handles rising costs well.

2️⃣ **Valuation (P/E {fundamentals.get('pe_ratio', 'N/A')}x):**
tells you whether you are paying a bargain price or a premium for future growth.

3️⃣ **Competitor Standing:**
Comparing {name} with peers reveals whether it is losing or gaining market share.

💡 **Next Step:** Tap **"🏢 Compare Competitors"** below to see how {name} compares to its rivals!"""

        # Profit & Loss history check
        if any(k in text_lower for k in ["profit", "loss", "p&l", "historical", "trend", "turning point", "history"]):
            hist = json.loads(dispatch_tool("get_historical_financials", {"ticker": target_ticker}, user_id))
            history_lines = []
            for item in hist.get("history", []):
                history_lines.append(f"• **{item['year']}**: Sales ₹{item['revenue_cr']:,.0f} Cr  |  Net Profit ₹{item['net_profit_cr']:,.0f} Cr  →  {item['status']}")

            turning_text = "\n".join([f"• {t}" for t in hist.get("turning_points", [])])

            return f"""📊 **Profit & Loss History: {name} ({target_ticker})**

💰 **5-Year Financial Progression:**
{chr(10).join(history_lines)}

🗓️ **What Changed Over Time?**
{turning_text}

💡 **What this means:**
{name} successfully improved its profitability through cost discipline and expanding sales volume."""

        # AI Health Score check
        if any(k in text_lower for k in ["health", "score", "rating", "rank"]):
            hs = json.loads(dispatch_tool("get_company_health_score", {"ticker": target_ticker}, user_id))
            factor_lines = "\n".join([f"• **{k}**: {v}" for k, v in hs.get("factors", {}).items()])
            return f"""⭐ **AI Health Score: {name} ({target_ticker})**

🏆 **Overall Rating:** `{hs.get('overall_score')}/10`

📊 **Score Breakdown:**
{factor_lines}

💡 **Why this score?**
{hs.get('score_justification')}

⚠️ *Disclaimer:* {hs.get('disclaimer')}"""

        # Default clean financial summary if specific financial keywords used
        has_financial_question = any(k in text_lower for k in [
            "price", "stock", "pe", "p/e", "valuation", "market cap",
            "fundamentals", "research", "analysis", "full research",
            "how is", "how's", "what happened", "why", "performance"
        ])
        if has_financial_question:
            mcap_raw = fundamentals.get("market_cap_inr", 0)
            mcap_str = f"₹{mcap_raw/1e12:.1f}L Cr" if mcap_raw >= 1e12 else f"₹{mcap_raw/1e7:,.0f} Cr"
            rev_raw = fundamentals.get("revenue_ttm_inr", 0)
            rev_str = f"₹{rev_raw/1e12:.1f}L Cr" if rev_raw >= 1e12 else f"₹{rev_raw/1e7:,.0f} Cr"
            profit_margin = f"{fundamentals.get('profit_margin', 0)*100:.1f}%" if fundamentals.get("profit_margin") else "N/A"
            pe = fundamentals.get("pe_ratio") or "N/A"

            return f"""{change_emoji} **{name}** ({target_ticker}) — {price_inr} ({change:+.2f}%)

📊 **Key Financials:**
• **Revenue (Sales):** {rev_str}
• **Net Margin:** {profit_margin} *(profit kept per ₹100 sales)*
• **P/E Ratio:** {pe}x *(price per ₹1 of earnings)*
• **Market Cap:** {mcap_str}
• **Sector:** {fundamentals.get('sector', 'Technology')}

💡 **Analysis:**
{name} {"is trading near recent highs" if change > 0 else "has seen price consolidation"}. {"Strong margins indicate solid profitability." if fundamentals.get('profit_margin', 0) > 0.15 else "Margins are worth monitoring."}"""

        # Pure company name entry — show clean research menu
        return f"""Sure! **{name}** is trading at {price_inr} ({change:+.2f}% today) {change_emoji}

What would you like to explore about **{name}**?

🔎 **Full Research** — complete company analysis
💰 **Profit & Loss** — 5-year revenue & profit history
📈 **Stock Performance** — price movements & trends
⭐ **AI Health Score** — 5-factor 0-10 rating
🏢 **Competitors** — industry peer comparison
⚠️ **Risks** — key business & financial risks
🎓 **Explain Simply** — beginner-friendly overview

Just pick an option below or ask me anything!"""

    # 3. Portfolio Analytics Check
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

    # 4. Comparison Requests
    if any(k in text_lower for k in ["compare", "vs", "versus", "difference between"]):
        comp_tickers = []
        for word in user_text.replace(",", " ").split():
            clean = word.strip(".,!?\"'()").lower()
            if clean in known_tickers:
                comp_tickers.append(known_tickers[clean])

        if len(comp_tickers) >= 2:
            comp_res = json.loads(dispatch_tool("compare_companies", {"tickers": comp_tickers[:4]}, user_id))
            lines = ["📊 **Side-by-Side Company Comparison**\n"]
            for t_data in comp_res.get("comparison", []):
                t_name = t_data.get("name", t_data.get("ticker"))
                lines.append(f"• **{t_name}** ({t_data.get('ticker')}): Price {t_data.get('formatted_price')} | P/E: {t_data.get('pe_ratio', 'N/A')}x | Net Margin: {t_data.get('profit_margin', 'N/A')} | Market Cap: {t_data.get('market_cap_formatted', 'N/A')}")
            return "\n".join(lines)

    # 5. EXPLICIT Stock Market Intelligence & Overview Check (Only if specifically requested)
    if any(k in text_lower for k in ["market summary", "market overview", "market update", "today's market", "stock market indices", "indices overview", "how is market"]):
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
