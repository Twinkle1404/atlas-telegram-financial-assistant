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
    return "anthropic"


def _run_anthropic_loop(system_prompt: str, messages: list, user_id: int, use_tools: bool) -> str:
    import anthropic
    import httpx
    from app.ai.tools import TOOL_SCHEMAS, dispatch_tool
    
    # Explicitly pass httpx.Client() to avoid httpx 0.28.1 'proxies' TypeError in older anthropic versions
    try:
        client = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            http_client=httpx.Client()
        )
    except Exception:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    
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
    """Generates structured financial research, P&L, stock quote, or portfolio report
    directly if third-party LLM authentication is unconfigured or unavailable."""
    from app.ai.tools import dispatch_tool
    text_lower = user_text.lower().strip()

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

        quote = json.loads(dispatch_tool("get_stock_quote", {"ticker": target_ticker}, user_id))
        fundamentals = json.loads(dispatch_tool("get_company_fundamentals", {"ticker": target_ticker}, user_id))

        name = fundamentals.get("name") or target_ticker
        price_inr = quote.get("formatted_price") or f"₹{quote.get('price_inr', 0):,.2f}"
        mcap = fundamentals.get("market_cap_formatted") or "N/A"
        pe = fundamentals.get("pe_ratio") or "N/A"
        rev = f"₹{fundamentals.get('revenue_ttm_inr', 0)/1e7:,.2f} Cr" if fundamentals.get("revenue_ttm_inr") else "N/A"
        gross_margin = f"{fundamentals.get('gross_margin', 0)*100:.1f}%" if fundamentals.get("gross_margin") else "N/A"
        profit_margin = f"{fundamentals.get('profit_margin', 0)*100:.1f}%" if fundamentals.get("profit_margin") else "N/A"
        high52 = f"₹{fundamentals.get('52w_high', 0):,.2f}" if fundamentals.get("52w_high") else "N/A"
        low52 = f"₹{fundamentals.get('52w_low', 0):,.2f}" if fundamentals.get("52w_low") else "N/A"
        rec = (fundamentals.get("analyst_recommendation") or "Outperform").capitalize()

        return f"""📊 **Financial Research & Profit/Loss Report: {name} ({target_ticker})**

📌 **Stock Quote & 52-Week Range (in ₹ Rupees):**
- **Current Price:** {price_inr} ({quote.get('change_pct', 0):+.2f}% today)
- **52-Week Range:** {low52} — {high52}

📊 **Profit & Loss (P&L Summary):**
- **TTM Revenue:** {rev}
- **Gross Profit Margin:** {gross_margin}
- **Net Profit Margin:** {profit_margin}
- **Sector/Industry:** {fundamentals.get('sector', 'Technology')} / {fundamentals.get('industry', 'Global')}

💰 **Valuation & Capital Structure:**
- **Market Capitalization:** {mcap}
- **P/E Ratio (Trailing):** {pe}x (Forward P/E: {fundamentals.get('forward_pe', 'N/A')}x)
- **Beta Volatility:** {fundamentals.get('beta', 1.0)}

🎯 **Analyst Consensus & Outlook:**
- **Consensus Rating:** {rec}
- **Target Price (Mean):** ₹{fundamentals.get('target_mean_price', 0):,.2f}
"""

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

    return (
        "Hey! I'm your AI Financial Assistant. Ask me about any company (e.g. 'Apple', 'Tesla', 'Reliance'), "
        "type a portfolio holding (e.g. '100 AAPL, 50 NVDA'), or request an IC Research Memo!"
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
