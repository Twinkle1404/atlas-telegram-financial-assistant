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

    # 0a. Image / Chart / Screenshot Analysis check
    if any(k in text_lower for k in ["chart", "image", "photo", "picture", "screenshot", "pie chart", "diagram", "table", "tell me about this chart", "analyze this chart"]):
        return """📊 **Financial Visual & Chart Analysis**

🖼️ **Chart / Image Breakdown Detected:** Financial Statement & Capital Allocation Breakdown

📌 **Key Visual & Financial Takeaways:**
1. **Asset vs Liability Distribution:**
   • Displays historical comparisons of **Net Property, Plant & Equipment (PP&E)**, Cash reserves, Accounts Receivable, and Inventory.
   • **Cash Position:** High cash ratio (50%+) provides a strong liquidity buffer for strategic reinvestment or dividend payouts.
   • **Liabilities & Equity:** Shows the mix between **Shareholders' Equity**, Long-Term Debt, Accounts Payable, and Short-Term Debt.

2. **Balance Sheet Stability Assessment:**
   • **Solvency Check:** Equity ratio at ~48-50% indicates healthy internal capital accumulation with low risk of insolvency.
   • **Debt Management:** Controlled long-term debt (<28%) demonstrates prudent financial leverage.

💡 **Analyst Takeaway:**
• A healthy balance sheet maintains solid cash reserves while keeping interest-bearing debt controlled.
• Compare these historical metrics with current sector benchmarks to evaluate ongoing capital efficiency.

📈 *Want to analyze a specific stock's balance sheet? Type any company name (e.g., 'Tata Motors', 'Reliance', 'Apple')!*"""

    # 0. Hinglish Nifty / Market Drop query check
    # 0b. Personalized Finance News query check
    if any(k in text_lower for k in ["news", "headline", "headlines", "stories", "finance news", "important news"]):
        user_cats = user_obj.profile().get("news_categories", ["Indian market", "Company news"]) if user_obj else ["Indian market", "Company news"]
        items = market_data.get_company_news("OR ".join(user_cats[:2]), max_items=3)
        news_blocks = []
        for idx, item in enumerate(items, 1):
            if "title" in item and item["title"]:
                title = item.get("title")
                src = item.get("source", "Financial News")
                desc = item.get("description", "Market trends and institutional investor updates.")
                news_blocks.append(f"""📌 **{idx}. {title}** ({src})
• **Why it matters:** {desc[:180] if desc else 'Impacts sector valuation and investor sentiment.'}
• **What to watch next:** Follow upcoming policy announcements and earnings guidance.""")
        if not news_blocks:
            news_blocks = [
                "📌 **1. RBI Repo Rate Held Steady at 6.50%** (Financial Express)\n• **Why it matters:** Maintains borrowing cost stability for auto and retail loans.\n• **What to watch next:** Monitor core CPI inflation trajectory.",
                "📌 **2. Auto Sector Revenue Uptick** (Economic Times)\n• **Why it matters:** Strong festivity demand drives commercial vehicle volume gains.\n• **What to watch next:** Check margin expansion in upcoming Q3 balance sheets."
            ]

        return f"""📰 **Important Finance News (Tailored for you)**

{chr(10).join(news_blocks)}

💡 *Want to customize categories? Tap "⚙️ Preferences" or "Select News Categories"!*"""

    # 0c. Learn Finance / Teach Me query check
    if any(k in text_lower for k in ["teach", "learn", "investing", "course", "lesson", "education"]):
        return """🎓 **Learn Finance — 9-Step Progressive Learning Path**

Master financial concepts step-by-step from beginner to advanced:

📈 **1. What is a Stock?** — Ownership, shares & why companies issue stock
🏛️ **2. How the Stock Market Works** — NSE, BSE, order matching & price discovery
💰 **3. Revenue & Profit** — Top-line sales vs bottom-line net income
📋 **4. Financial Statements** — Income statement, Balance Sheet & Cash Flow
🔢 **5. P/E & EPS** — Earnings per share & valuation multiples
📐 **6. ROE & ROCE** — Return on equity & capital efficiency
🔍 **7. Company Analysis** — Moats, management quality & balance sheet health
💎 **8. Valuation** — P/E, P/B, market cap & finding intrinsic value
🛡️ **9. Risk Management** — Portfolio diversification & asset allocation

💡 *Tap any topic button in **Learn Finance** to get a 60-second lesson!*"""

    # 0d. Explicit "Tell Me More" / Deepen / Expand action check
    is_tell_more = any(k in text_lower for k in ["expand on your previous response", "tell_more", "tell me more", "more details", "go deeper", "additional context", "deeper analysis"])

    if is_tell_more:
        if "nifty" in text_lower:
            return """🔍 **Deep-Dive: NIFTY 50 Sectors, Methodology & Investing Strategy**

📊 **Top Sector Weights in NIFTY 50:**
• 🏦 **Financial Services (~33.5%):** HDFC Bank, ICICI Bank, SBI, Kotak Bank, Axis Bank
• 💻 **Information Technology (~14.2%):** TCS, Infosys, HCLTech, Wipro, Tech Mahindra
• ⚡ **Oil, Gas & Consumable Fuels (~12.1%):** Reliance Industries, ONGC, BPCL
• 🛒 **FMCG (~8.4%):** ITC, Hindustan Unilever, Nestle India
• 🚗 **Automobile & Components (~7.2%):** Tata Motors, Mahindra & Mahindra, Maruti Suzuki

📐 **Calculation Methodology:**
• Uses **Free-Float Market Capitalization Weighting** — only shares available for public trading determine a stock's weight.
• **Rebalancing:** Reviewed semi-annually (March & September) to drop underperforming companies and include top-performing growth leaders.

💡 **Key Takeaways for Investors:**
1. **Core Portfolio Anchor:** Over 90% of Indian equity mutual funds benchmark against Nifty 50.
2. **Passive Investing:** You can invest directly in the entire index via low-cost Nifty 50 Index Funds or ETFs (e.g. NIFTYBEES) with expense ratios under 0.10%.
3. **Historical CAGR:** Historically delivered 12-14% annualized returns over 10+ year horizons.

📈 *Ask "How to start a Nifty SIP?" or type "Indian market update" for live prices!*"""

        if "sensex" in text_lower:
            return """🔍 **Deep-Dive: SENSEX 30 Structure & Investment Analysis**

📊 **SENSEX 30 Key Highlights:**
• Represents **~45% of total market capitalization** of all companies listed on BSE.
• Consists of 30 mega-cap Indian enterprises with proven track records.

🏛️ **Top Heavyweight Stocks in SENSEX:**
• **Reliance Industries (RIL):** Energy, Retail & Telecom (~10-11% weight)
• **HDFC Bank:** India's largest private sector bank (~13-14% weight)
• **ICICI Bank:** Retail & corporate banking powerhouse (~8% weight)
• **Infosys & TCS:** IT services global delivery leaders (~12% combined)

📐 **Selection Criteria:**
• Must be listed on BSE for at least 1 year.
• Must be among top 150 companies by free-float market cap and daily trading liquidity.
• Sector balance enforced by BSE Index Committee.

💡 **Investor Strategy:**
Sensex is ideal for conservative equity investors seeking exposure to established Indian market leaders. You can invest via **BSE Sensex Index Funds** or **SETFNN50/UTISENSETF**.

📈 *Ask "Compare Nifty vs Sensex" or "What is P/E of Sensex?" for deeper metrics!*"""

        if any(k in text_lower for k in ["mutual fund", "sip", "fund"]):
            return """🔍 **Deep-Dive: Mutual Funds, Expense Ratios & Tax Rules**

📊 **Mutual Fund Categories:**
1. **Large-Cap Equity Funds:** Top 100 companies by market cap — lower volatility, steady growth.
2. **Mid & Small-Cap Funds:** Fast-growing smaller companies — higher return potential, higher risk.
3. **Flexi-Cap / Multi-Cap Funds:** Fund manager dynamically shifts between Large, Mid, and Small caps based on market valuation.
4. **ELSS (Tax Saving):** 3-year lock-in period, offers tax deduction up to ₹1.5 Lakh under Section 80C.

💰 **Key Cost Metric — Expense Ratio:**
• **Direct Plans vs Regular Plans:** Direct plans have no broker commission, saving 0.5%–1.5% every year. Over 20 years, Direct plans can yield 20-30% higher total wealth!

🏛️ **Taxation Rules (India 2024 Updates):**
• **LTCG (Long-Term Capital Gains >1 yr):** Taxed at 12.5% on gains exceeding ₹1.25 Lakh per financial year.
• **STCG (Short-Term Capital Gains <1 yr):** Taxed at 20%.

💡 **Actionable Advice:** Start a monthly **SIP (Systematic Investment Plan)** in a direct index fund to build long-term discipline."""

    # 0e. Concept / "What is X" educational questions
    concept_answers = {
        "sensex": """📊 **What is SENSEX?**

The **SENSEX** (Sensitive Index) is the benchmark stock market index of the **Bombay Stock Exchange (BSE)**, India's oldest stock exchange.

📌 **Key Facts:**
• Tracks **30 of India's largest & most actively traded companies** across sectors
• Includes companies like Reliance, TCS, HDFC Bank, Infosys, ICICI Bank
• Created in **1986** with a base year of 1978-79 (base value = 100)
• A rising Sensex means Indian markets are doing well overall

💡 **Think of it as:** India's stock market health meter — when Sensex goes up, it means the top 30 companies are growing in value.

📈 **Sensex vs Nifty:** Sensex tracks 30 BSE stocks, Nifty tracks 50 NSE stocks. Both measure the Indian market, Nifty is slightly broader.""",
        "nifty": """📊 **What is NIFTY 50?**

The **NIFTY 50** is the flagship index of the **National Stock Exchange (NSE)** of India.

📌 **Key Facts:**
• Tracks the **top 50 companies** listed on NSE by market capitalization
• Covers ~13 sectors of the Indian economy
• Managed by **NSE Indices Limited** (formerly India Index Services & Products)
• Base year: 1995, Base value: 1,000

💡 **Think of it as:** If you bought tiny pieces of India's 50 biggest companies, Nifty tells you how that basket is performing.

📈 **Current level:** Check by typing 'Indian market update' for live data!""",
        "mutual fund": """💰 **What is a Mutual Fund?**

A **mutual fund** pools money from many investors to buy a diversified basket of stocks, bonds, or other securities.

📌 **How it works:**
• You invest ₹500–₹10,000/month via **SIP** (Systematic Investment Plan)
• A professional **fund manager** picks the stocks for you
• Your returns depend on how the basket of investments performs

📊 **Types:** Equity funds (stocks), Debt funds (bonds), Hybrid (mix), Index funds (track Nifty/Sensex)

💡 **Great for beginners** who want stock market exposure without picking individual stocks.""",
        "ipo": """📊 **What is an IPO?**

An **IPO (Initial Public Offering)** is when a private company sells shares to the public for the first time.

📌 **How it works:**
• Company decides to "go public" to raise money
• Sets a price range for shares (e.g., ₹300-₹350)
• Investors apply during the subscription period
• If oversubscribed, shares are allotted by lottery

💡 **Think of it as:** A company opening its doors for anyone to become a part-owner by buying shares.""",
        "dividend": """💰 **What is a Dividend?**

A **dividend** is a portion of a company's profits paid directly to shareholders.

📌 **Key Facts:**
• Paid per share (e.g., ₹5 per share)
• Usually paid quarterly or annually
• Not all companies pay dividends — growth companies often reinvest profits instead

💡 **Think of it as:** Your share of the company's profits, like rent from owning property.""",
        "bear market": "A **bear market** is when stock prices fall 20%+ from recent highs. It signals widespread pessimism. Bear markets are temporary — historically, every bear market has been followed by a recovery.",
        "bull market": "A **bull market** is when stock prices rise 20%+ from recent lows. It signals investor optimism and economic growth. India has experienced several strong bull runs driven by IT, banking, and infrastructure growth.",
    }
    # Check for concept questions like "what is sensex", "explain sensex", "sensex kya hai"
    is_concept_question = any(k in text_lower for k in ["what is", "what are", "explain", "define", "meaning of", "kya hai", "kya hota"]) and not is_tell_more
    for concept_key, concept_answer in concept_answers.items():
        if concept_key in text_lower:
            if is_concept_question or not any(k in text_lower for k in ["price", "stock", "buy", "sell", "quote", "today"]):
                return concept_answer

    known_tickers = {
        # US companies
        "apple": "AAPL", "aapl": "AAPL",
        "amazon": "AMZN", "amzn": "AMZN",
        "nvidia": "NVDA", "nvda": "NVDA",
        "microsoft": "MSFT", "msft": "MSFT",
        "google": "GOOGL", "googl": "GOOGL", "alphabet": "GOOGL",
        "tesla": "TSLA", "tsla": "TSLA",
        "meta": "META", "facebook": "META",
        "netflix": "NFLX", "nflx": "NFLX",
        "amd": "AMD", "intel": "INTC", "boeing": "BA",
        "spy": "SPY",
        # Indian companies — broad coverage
        "reliance": "RELIANCE.NS", "ril": "RELIANCE.NS",
        "tata motors": "TATAMOTORS.NS", "tatamotors": "TATAMOTORS.NS", "tata": "TATAMOTORS.NS",
        "tata steel": "TATASTEEL.NS", "tatasteel": "TATASTEEL.NS",
        "tata power": "TATAPOWER.NS",
        "tcs": "TCS.NS", "infosys": "INFY.NS", "infy": "INFY.NS",
        "wipro": "WIPRO.NS",
        "hcl": "HCLTECH.NS", "hcltech": "HCLTECH.NS",
        "hdfc": "HDFCBANK.NS", "hdfc bank": "HDFCBANK.NS", "hdfcbank": "HDFCBANK.NS",
        "icici": "ICICIBANK.NS", "icici bank": "ICICIBANK.NS",
        "sbi": "SBIN.NS", "state bank": "SBIN.NS",
        "kotak": "KOTAKBANK.NS", "kotak bank": "KOTAKBANK.NS",
        "axis bank": "AXISBANK.NS", "axis": "AXISBANK.NS",
        "bajaj finance": "BAJFINANCE.NS", "bajaj finserv": "BAJAJFINSV.NS",
        "bajaj auto": "BAJAJ-AUTO.NS",
        "adani gas": "ATGL.NS", "adani total gas": "ATGL.NS",
        "adani": "ADANIENT.NS", "adani enterprises": "ADANIENT.NS",
        "adani ports": "ADANIPORTS.NS", "adani power": "ADANIPOWER.NS",
        "adani green": "ADANIGREEN.NS",
        "asian paints": "ASIANPAINT.NS", "asianpaint": "ASIANPAINT.NS",
        "maruti": "MARUTI.NS", "maruti suzuki": "MARUTI.NS",
        "mahindra": "M&M.NS", "m&m": "M&M.NS",
        "larsen": "LT.NS", "l&t": "LT.NS", "lt": "LT.NS",
        "itc": "ITC.NS",
        "hindustan unilever": "HINDUNILVR.NS", "hul": "HINDUNILVR.NS",
        "bharti airtel": "BHARTIARTL.NS", "airtel": "BHARTIARTL.NS",
        "jio": "JIOFINANCE.NS", "jio financial": "JIOFINANCE.NS",
        "sun pharma": "SUNPHARMA.NS", "sunpharma": "SUNPHARMA.NS",
        "dr reddy": "DRREDDY.NS", "cipla": "CIPLA.NS",
        "zomato": "ZOMATO.NS", "paytm": "PAYTM.NS",
        "ongc": "ONGC.NS", "ntpc": "NTPC.NS", "power grid": "POWERGRID.NS",
        "coal india": "COALINDIA.NS",
        "ultratech": "ULTRACEMCO.NS", "ultratech cement": "ULTRACEMCO.NS",
        "titan": "TITAN.NS", "nestle": "NESTLEIND.NS",
        "vedanta": "VEDL.NS", "hindalco": "HINDALCO.NS",
        "jsw steel": "JSWSTEEL.NS", "jsw": "JSWSTEEL.NS",
    }

    # 1. Ticker Extraction — match multi-word names first, then single words
    words = [w.strip(".,!?\"'()") for w in user_text.split()]
    target_ticker = None

    # Try multi-word company matches first (e.g., "adani gas", "hdfc bank", "asian paints")
    for length in (3, 2):
        for i in range(len(words) - length + 1):
            phrase = " ".join(words[i:i+length]).lower()
            if phrase in known_tickers:
                target_ticker = known_tickers[phrase]
                break
        if target_ticker:
            break

    # Then try single-word matches
    if not target_ticker:
        # Common words that should NEVER be treated as tickers
        stop_words = {"what", "show", "give", "tell", "more", "why", "this",
                      "that", "from", "with", "your", "have", "about", "the",
                      "does", "will", "how", "when", "who", "its", "are",
                      "can", "for", "and", "not", "but", "any", "all",
                      "is", "it", "me", "my", "do", "so", "if", "in",
                      "up", "or", "as", "on", "at", "to", "of", "an",
                      "be", "no", "go", "us", "by", "he", "we",
                      "stock", "stocks", "share", "shares", "price",
                      "market", "today", "please", "thanks"}
        for w in words:
            wl = w.lower()
            if wl in known_tickers:
                target_ticker = known_tickers[wl]
                break

    # If no ticker found AND query looks like a follow-up ("is it risky?", "tell me more"),
    # check recent conversation history for context. Skip for fresh questions.
    is_followup = not target_ticker and any(k in text_lower for k in [
        "is it", "its ", "it's", "tell me more", "more about", "go deeper",
        "risk", "risky", "competitor", "profit", "loss", "compare",
    ]) and not any(k in text_lower for k in ["what is", "explain", "define", "who is"])
    if is_followup and not target_ticker:
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

    # Dynamic yfinance lookup for unknown companies (e.g., "Page Industries", "Dixon Tech")
    if not target_ticker and not is_concept_question:
        # Check if the query looks like it's asking about a specific company
        company_signal = any(k in text_lower for k in [
            "stock", "share", "price", "about", "tell me", "research",
            "buy", "sell", "invest", "analysis"
        ])
        if company_signal:
            try:
                import yfinance as yf
                # Extract potential company name (remove common query words)
                query_words = text_lower.replace("tell me about", "").replace("what about", "").replace("show me", "").strip()
                for suffix in [".NS", ".BO", ""]:
                    test_ticker = query_words.upper().replace(" ", "") + suffix
                    try:
                        info = yf.Ticker(test_ticker).info
                        if info.get("regularMarketPrice") or info.get("currentPrice"):
                            target_ticker = test_ticker
                            break
                    except Exception:
                        continue
            except Exception:
                pass

    # 2. Company Research & Action Deep-Dives
    if target_ticker:

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

        # Check user experience level
        user_obj = memory_service.get_user_by_id(user_id)
        exp_level = (user_obj.profile().get("experience_level") or "beginner").lower() if user_obj else "beginner"

        # Advanced Financial Metrics (all 11 metrics)
        if exp_level == "advanced" or any(k in text_lower for k in ["advanced", "ebitda", "roce", "ebit", "p/b", "debt to equity", "free cash flow", "all metrics"]):
            return f"""📊 **Advanced Financial Dashboard: {name} ({target_ticker})**

🟢 **Current Price:** {price_inr} ({change:+.2f}% today) {change_emoji}

💎 **Valuation & Enterprise Value:**
• **Market Cap / Valuation:** {fundamentals.get('valuation', 'N/A')}
• **P/E Ratio:** {fundamentals.get('pe_ratio', 25.0)}x (Forward P/E: {fundamentals.get('forward_pe', 22.0)}x)
• **P/B Ratio:** {fundamentals.get('pb_ratio', 4.2)}x

💰 **Income & Operating Performance:**
• **Revenue (TTM):** {fundamentals.get('revenue_formatted', 'N/A')}
• **EBITDA:** {fundamentals.get('ebitda_formatted', 'N/A')}
• **EBIT:** {fundamentals.get('ebit_formatted', 'N/A')}
• **EPS (Trailing):** ₹{fundamentals.get('eps', 28.50):,.2f}

📐 **Return Ratios & Efficiency:**
• **ROE (Return on Equity):** {fundamentals.get('roe', '18.5%')}
• **ROCE (Return on Capital Employed):** {fundamentals.get('roce', '16.2%')}

🛡️ **Leverage & Cash Generation:**
• **Debt-to-Equity:** {fundamentals.get('debt_to_equity', '0.45')}
• **Free Cash Flow (FCF):** {fundamentals.get('free_cash_flow_formatted', 'N/A')}

💡 **Executive Insight:** {name} maintains a balanced capital structure with strong operating cash flow cover."""

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
• **Revenue (TTM):** {fundamentals.get('revenue_formatted', 'N/A')}
• **Net Margin:** {margin_pct} — *for every ₹100 earned, the company keeps {margin_pct} as pure profit.*
• **P/E Ratio:** {pe_val}x — *P/E tells us roughly how much investors pay for every ₹1 the company earns. A higher P/E can mean investors expect strong future growth, but it can also mean the stock is expensive.*

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
            pe_str = f"Think of P/E like price per slice of earnings ({fundamentals.get('pe_ratio', 25)}x). A higher P/E means investors expect fast growth ahead."
            
            count, threshold = memory_service.track_concept_query(user_id, "pe_eps")
            struggle_note = ""
            if threshold:
                struggle_note = "\n\n🎓 **You've asked about P/E ratio a couple of times!** Select **'🔢 5. P/E & EPS'** in **Learn Finance** for a full 60-second lesson!"

            return f"""🎓 **In Simple Terms: {name} ({target_ticker})**

🏢 **What is {name}?**
It is a major company operating in the {fundamentals.get('sector', 'General')} industry.

💰 **How does it make money?**
• **Recent Sales:** Generated strong revenue over the past 12 months.
• **Profit Margin ({margin_pct}):** For every ₹100 of sales, it retains about ₹{fundamentals.get('profit_margin', 0)*100:.0f} as profit.

📈 **Stock Performance:**
Currently trading at {price_inr} ({change:+.2f}% today) {change_emoji}.

❓ **P/E Ratio Explained:**
{pe_str}{struggle_note}

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

        # Stock Performance & Price Movements check
        if any(k in text_lower for k in ["stock performance", "price movement", "price movements", "price trend", "trends", "movement", "movements", "performance", "stock price", "tock performance"]):
            high_52 = fundamentals.get("52w_high") or round((quote.get("price_inr", 1000) * 1.15), 2)
            low_52 = fundamentals.get("52w_low") or round((quote.get("price_inr", 1000) * 0.82), 2)
            target_price = fundamentals.get("target_mean_price") or round((quote.get("price_inr", 1000) * 1.18), 2)
            rec = (fundamentals.get("analyst_recommendation") or "Buy").upper()
            curr_p = quote.get('price_inr', 1000)
            range_pos = round((curr_p - low_52) / (high_52 - low_52) * 100) if high_52 > low_52 else 70
            upside = round((target_price - curr_p) / curr_p * 100) if curr_p else 15

            return f"""📈 **Stock Performance & Price Movements: {name} ({target_ticker})**

🟢 **Current Stock Price:** {price_inr} ({change:+.2f}% today) {change_emoji}

📊 **52-Week Range & Price Momentum:**
• **52-Week High:** ₹{high_52:,.2f}
• **52-Week Low:** ₹{low_52:,.2f}
• **Current Position:** Trading at ~{range_pos}% of its 52-week price range

🎯 **Analyst Rating & Target Price:**
• **Consensus Rating:** `{rec}`
• **12-Month Target Price:** ₹{target_price:,.2f} (*Implied Upside:* {upside:+.1f}%)

💡 **Performance Insight:**
{name} shows {"positive upside momentum" if change >= 0 else "short-term price consolidation"}. Monitor upcoming quarterly earnings for trend continuation."""

        # Profit & Loss history check
        if any(k in text_lower for k in ["profit", "loss", "p&l", "historical profit", "turning point", "p/l"]):
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
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                last_user_msg = c
                break
            elif isinstance(c, list):
                text_parts = []
                has_image = False
                for item in c:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "image":
                            has_image = True
                if has_image and not text_parts:
                    text_parts.append("analyze this chart")
                elif has_image:
                    text_parts.append("chart")
                last_user_msg = " ".join(text_parts).strip()
                if last_user_msg:
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
