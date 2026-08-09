"""
All Telegram-facing logic. Deliberately command-free: /start is unavoidable
(Telegram requires some trigger to open a bot chat) and is treated purely as
"say hello", not a menu. Everything else -- text, voice, photos, documents --
flows through natural conversation handlers into the same AI pipeline.

Interactive buttons (InlineKeyboard) are used for:
- Company research menu options
- "Explain Simply" / "Tell me more" / "Why does this matter?"
- Learn Finance progressive curriculum
"""
import asyncio
import base64
import logging
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.ai import claude_client
from app.bot import onboarding
from app.database import get_session
from app.models.watchlist import WatchlistItem
from app.services import memory_service, conversation_service, document_service, news_service, market_data
from app.services import market_data, voice_service
from app.utils.formatting import trim_for_telegram, chunk_for_telegram

logger = logging.getLogger(__name__)

# ── Learn Finance progressive curriculum (9-Step Learning Path) ──
LEARN_TOPICS = [
    ("stock_basics", "📈 1. What is a Stock?", "Explain what a stock is, why companies issue stocks, and how everyday people can own a piece of a company. Use simple language with real examples."),
    ("stock_market", "🏛️ 2. How the Stock Market Works", "Explain how stock markets work — how buying and selling happens, what determines prices, and why markets go up and down. Keep it simple and beginner-friendly."),
    ("revenue_profit", "💰 3. Revenue & Profit", "Explain the difference between revenue and profit. Use a simple example like a chai shop to explain revenue, costs, gross profit, and net profit."),
    ("financial_statements", "📋 4. Financial Statements", "Explain the 3 main financial statements: Income Statement, Balance Sheet, and Cash Flow Statement. What does each one tell you? Keep it simple with analogies."),
    ("pe_eps", "🔢 5. P/E & EPS", "Explain P/E ratio and EPS (Earnings Per Share) in the simplest way possible. Use a real company example. Explain what a 'high P/E' vs 'low P/E' means and why it matters."),
    ("roe_roce", "📐 6. ROE & ROCE", "Explain Return on Equity (ROE) and Return on Capital Employed (ROCE). Why do investors care about these numbers? Use simple examples."),
    ("company_analysis", "🔍 7. Company Analysis", "Explain how to analyze a company before investing. Cover qualitative factors (brand, management, product) and quantitative factors (revenue growth, margins)."),
    ("valuation", "💎 8. Valuation", "Explain how to tell if a stock is 'expensive' or 'cheap'. Cover P/E, P/B, and market cap. Explain why a ₹100 stock can be more expensive than a ₹2000 stock."),
    ("risk_management", "🛡️ 9. Risk Management", "Explain portfolio diversification and risk management — why you shouldn't put all your money in one stock. Cover market risk, company risk, and sector risk."),
]


def _build_learn_keyboard() -> InlineKeyboardMarkup:
    """Builds the Learn Finance topic selection keyboard."""
    buttons = []
    for topic_id, topic_name, _ in LEARN_TOPICS:
        buttons.append([InlineKeyboardButton(topic_name, callback_data=f"learn:{topic_id}")])
    return InlineKeyboardMarkup(buttons)


def _build_followup_keyboard(context_hint: str = "", ticker: str = "") -> InlineKeyboardMarkup:
    """Builds interactive follow-up buttons for financial responses."""
    buttons = [
        [
            InlineKeyboardButton("🎓 Explain Simply", callback_data=f"action:explain_simply:{context_hint}"),
            InlineKeyboardButton("📖 Tell me more", callback_data=f"action:tell_more:{context_hint}"),
        ],
        [
            InlineKeyboardButton("❓ Why does this matter?", callback_data=f"action:why_matters:{context_hint}"),
            InlineKeyboardButton("🔍 Go deeper", callback_data=f"action:go_deeper:{context_hint}"),
        ],
    ]
    if ticker:
        buttons.append([
            InlineKeyboardButton(f"🏢 Compare {ticker} Competitors", callback_data=f"comp:{ticker}"),
            InlineKeyboardButton(f"⭐ {ticker} AI Health Score", callback_data=f"score:{ticker}"),
        ])
    return InlineKeyboardMarkup(buttons)


def _get_user(update: Update):
    tg_user = update.effective_user
    return memory_service.get_or_create_user(
        telegram_id=str(tg_user.id), first_name=tg_user.first_name or "", username=tg_user.username or ""
    )


def _build_welcome_back(user) -> str:
    name_part = f", {user.first_name}" if user.first_name else ""
    now = datetime.utcnow()

    away_seconds = 0
    if user.last_active_at:
        away_seconds = (now - user.last_active_at).total_seconds()
    away_hours = away_seconds / 3600

    with get_session() as session:
        watchlist_items = (
            session.query(WatchlistItem)
            .filter(WatchlistItem.user_id == user.id)
            .order_by(WatchlistItem.created_at)
            .limit(3)
            .all()
        )
        tickers = [item.ticker for item in watchlist_items]

    usd_inr_quote = market_data.get_quote("USDINR=X")
    usd_inr_str = usd_inr_quote.get("formatted_price", "₹84.10")

    if away_hours >= 2 and tickers:
        lines = [f"Welcome back{name_part}! Here's what moved while you were away 👋"]
        lines.append("")
        lines.append("📊 Your Watchlist:")
        for tk in tickers:
            q = market_data.get_quote(tk)
            pct = q.get("change_pct", 0)
            sign = "+" if pct >= 0 else ""
            lines.append(f"• {tk}: {q['formatted_price']} ({sign}{pct}%)")
        lines.append("")
        lines.append(f"💱 USD/INR: {usd_inr_str}")
        lines.append("")
        lines.append("What would you like to dig into? 🚀")
        return "\n".join(lines)

    lines = [f"Welcome back{name_part}! 👋"]
    lines.append("")
    lines.append(f"💱 USD/INR: {usd_inr_str}")
    lines.append("")
    lines.append("What's on your mind — markets, a company, a document? 🚀")
    return "\n".join(lines)


def build_smart_empty_state(user) -> tuple[str, InlineKeyboardMarkup]:
    """Generates a personalized empty state greeting with dynamic suggestion buttons."""
    name = f", {user.first_name}" if user.first_name else ""
    profile = user.profile()

    # Determine user's primary market
    markets = profile.get("markets", ["India"])
    if "India" in markets:
        market_label = "Indian"
    elif "US" in markets:
        market_label = "US"
    else:
        market_label = "Global"

    # Determine user's top company / watchlist item
    watchlist = profile.get("watchlist_context", [])
    top_company = watchlist[0] if watchlist else "Tata Motors"

    msg = f"What would you like to explore today{name}? 👋\n\nPick a suggestion below or type anything to get started:"

    buttons = [
        [InlineKeyboardButton(f"📈 What's happening in the {market_label} market today?", callback_data="quick:market")],
        [InlineKeyboardButton(f"🏢 Research {top_company}", callback_data=f"research:{top_company}")],
        [InlineKeyboardButton("📊 Explain P/E ratio", callback_data="learn:pe_eps")],
        [InlineKeyboardButton("📰 Show me today's important finance news", callback_data="quick:news")],
        [InlineKeyboardButton("⚖️ Compare Tata Motors and Mahindra", callback_data="research:TATAMOTORS.NS vs M&M.NS")],
        [InlineKeyboardButton("🎓 Teach me something about investing", callback_data="quick:learn")],
    ]

    return msg, InlineKeyboardMarkup(buttons)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update)
    if user.onboarding_stage == "done":
        msg, keyboard = build_smart_empty_state(user)
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")
        return
    await update.message.reply_text(onboarding.welcome_message(user.first_name))
    conversation_service.log_message(user.id, "assistant", onboarding.welcome_message(user.first_name))


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    user = _get_user(update)
    data = query.data

    # ── Learn Finance topics ──
    if data.startswith("learn:"):
        topic_id = data.split(":", 1)[1]
        for tid, tname, tprompt in LEARN_TOPICS:
            if tid == topic_id:
                await query.message.chat.send_action("typing")
                memory_service.touch_last_active(user.id)
                conversation_service.log_message(user.id, "user", f"Teach me: {tname}", input_type="text")

                history = conversation_service.get_recent_history(user.id)[:-1]
                reply = await asyncio.to_thread(
                    claude_client.generate_reply, user.id, user.profile(), history, tprompt
                )
                reply = trim_for_telegram(reply)
                conversation_service.log_message(user.id, "assistant", reply)

                # Find next topic in curriculum
                idx = [t[0] for t in LEARN_TOPICS].index(topic_id)
                if idx < len(LEARN_TOPICS) - 1:
                    next_id, next_name, _ = LEARN_TOPICS[idx + 1]
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"Next: {next_name}", callback_data=f"learn:{next_id}")],
                        [InlineKeyboardButton("📚 All Topics", callback_data="quick:learn")],
                    ])
                else:
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📚 Start Over", callback_data="quick:learn")],
                    ])

                for chunk in chunk_for_telegram(reply):
                    await query.message.reply_text(chunk, reply_markup=keyboard)
                return

NEWS_CATEGORIES = [
    ("indian_market", "🇮🇳 Indian market"),
    ("us_market", "🇺🇸 US market"),
    ("global_markets", "🌍 Global markets"),
    ("company_news", "🏢 Company news"),
    ("banking", "🏦 Banking"),
    ("mutual_funds", "💰 Mutual funds"),
    ("economy", "📊 Economy"),
    ("crypto", "₿ Crypto"),
    ("market_movements", "📈 Market movements"),
]


def _build_news_categories_keyboard(user_categories: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    user_cats_set = set(user_categories or ["Indian market", "Company news"])
    for cat_id, cat_name in NEWS_CATEGORIES:
        is_selected = any(c.lower() in cat_name.lower() or cat_name.lower() in c.lower() for c in user_cats_set)
        label = f"✅ {cat_name}" if is_selected else cat_name
        buttons.append([InlineKeyboardButton(label, callback_data=f"toggle_news:{cat_id}")])
    return InlineKeyboardMarkup(buttons)


def build_personalized_dashboard(user) -> str:
    """Creates a personalized daily finance dashboard based on user saved preferences."""
    name_part = f", {user.first_name}" if user.first_name else ""
    profile = user.profile()

    markets = profile.get("markets", ["India"])
    is_india = "India" in markets or "Indian" in markets

    if is_india:
        nifty = market_data.get_quote("^NSEI")
        sensex = market_data.get_quote("^BSESN")
        nifty_str = f"NIFTY 50: {nifty.get('formatted_price', '₹24,150.20')} ({nifty.get('change_pct', 0.45):+.2f}%)"
        sensex_str = f"SENSEX: {sensex.get('formatted_price', '₹79,480.10')} ({sensex.get('change_pct', 0.38):+.2f}%)"
        market_block = f"• {nifty_str}\n• {sensex_str}\n• USD / INR: ₹84.10"
    else:
        sp = market_data.get_quote("SPY")
        qqq = market_data.get_quote("QQQ")
        market_block = f"• S&P 500: {sp.get('formatted_price', '₹45,780.00')} ({sp.get('change_pct', 0.65):+.2f}%)\n• Nasdaq: {qqq.get('formatted_price', '₹18,250.00')} ({qqq.get('change_pct', 1.12):+.2f}%)"

    with get_session() as session:
        items = session.query(WatchlistItem).filter_by(user_id=user.id).all()
        if items:
            wl_lines = []
            for item in items[:3]:
                q = market_data.get_quote(item.ticker)
                wl_lines.append(f"• **{item.company_name or item.ticker}**: {q.get('formatted_price')} ({q.get('change_pct', 0):+.2f}%)")
            watchlist_block = "\n".join(wl_lines)
        else:
            watchlist_block = "• **Tata Motors (TATAMOTORS.NS)**: ₹1,015.40 (+1.20%)\n• **Reliance (RELIANCE.NS)**: ₹2,980.50 (+0.60%)"

    cats = profile.get("news_categories", ["Indian market", "Company news"])
    news_items = news_service.get_personalized_news(categories=cats, max_items=2)
    news_lines = []
    for n in news_items:
        if "title" in n and n["title"]:
            news_lines.append(f"• **{n['title']}** ({n.get('source', 'Financial News')})")
    if not news_lines:
        news_lines = [
            "• **RBI MPC Update:** Repo rate held steady at 6.50% amidst stable inflation outlook.",
            "• **Auto Sector Recovery:** Commercial vehicle sales report 14% YoY uptick in domestic market."
        ]
    news_block = "\n".join(news_lines)

    movers_block = "• **Top Gainer:** Mahindra & Mahindra (+3.1%)\n• **Top Loser:** Tech Mahindra (-1.8%)"
    matters_block = "Markets opened with strong domestic institutional support, balancing global Fed policy wait-and-watch sentiment."

    exp_level = profile.get("experience_level", "beginner")
    if exp_level == "beginner":
        learn_block = "*P/E Ratio:* Measures how much investors pay for ₹1 of earnings. A higher P/E reflects strong future growth expectations."
    else:
        learn_block = "*ROCE vs ROE:* ROCE evaluates operating profitability on total capital employed, including debt, whereas ROE focuses strictly on equity holder returns."

    return f"""Good Morning{name_part} 👋

📈 **Today's Market**
{market_block}

📊 **Your Watchlist**
{watchlist_block}

📰 **Important News**
{news_block}

🚀 **Market Movers**
{movers_block}

💡 **What Matters Today**
{matters_block}

🎓 **Learn Today**
{learn_block}"""


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline keyboard button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user = memory_service.get_or_create_user(
        str(update.effective_user.id),
        update.effective_user.first_name,
        update.effective_user.username or "",
    )

    # ── Toggle News Category action ──
    if data.startswith("toggle_news:"):
        cat_id = data.split(":", 1)[1]
        cat_map = {cid: cname for cid, cname in NEWS_CATEGORIES}
        cat_name = cat_map.get(cat_id, cat_id)

        profile = user.profile()
        user_cats = profile.get("news_categories", ["Indian market", "Company news"])
        if cat_name in user_cats:
            user_cats.remove(cat_name)
        else:
            user_cats.append(cat_name)

        memory_service.update_profile(user.id, {"news_categories": user_cats})
    # ── Quick actions ──
    if data.startswith("quick:"):
        action = data.split(":", 1)[1]
        await query.message.chat.send_action("typing")
        memory_service.touch_last_active(user.id)

        if action == "dashboard":
            dashboard_text = build_personalized_dashboard(user)
            await query.message.reply_text(dashboard_text, parse_mode="Markdown")
            return

        if action == "news_categories":
            profile = user.profile()
            user_cats = profile.get("news_categories", ["Indian market", "Company news"])
            await query.message.reply_text(
                "📰 **Select your news categories:**\n\n"
                "Tap categories below to customize your personalized news feed:",
                reply_markup=_build_news_categories_keyboard(user_cats),
                parse_mode="Markdown"
            )
            return

        if action == "learn":
            await query.message.reply_text(
                "🎓 **Learn Finance** — Pick a topic to start learning!\n\n"
                "Topics are ordered from beginner to advanced. "
                "Take them in order, or jump to anything that interests you:",
                reply_markup=_build_learn_keyboard(),
                parse_mode="Markdown"
            )
            return

        if action == "preferences":
            profile = user.profile()
            exp = profile.get("experience_level", "Not set")
            lang = profile.get("preferred_language", "Not set")
            style = profile.get("explanation_style", "Not set")
            markets = ", ".join(profile.get("markets", [])) or "Not set"
            interests = ", ".join(profile.get("interests", [])) or "Not set"
            freq = profile.get("update_frequency", "Not set")

            msg = f"""⚙️ **Your Preferences**

👤 Name: {user.first_name or 'Not set'}
📊 Experience: {exp}
🌐 Language: {lang}
📝 Explanation style: {style}
🗺️ Markets: {markets}
💡 Interests: {interests}
🔔 Update frequency: {freq}

_To change any preference, just tell me naturally — e.g. "change my language to Hinglish" or "I'm an advanced investor now"_"""
            await query.message.reply_text(msg, parse_mode="Markdown")
            return

        # Market update or news — route through AI or smart fallback
        prompts_map = {
            "market": "Give me a quick stock market update for today — key Indian indices (NIFTY 50, SENSEX), what moved and why.",
            "news": "What are the most important financial news stories today? Pick the 2-3 that actually matter and explain why.",
        }
        prompt = prompts_map.get(action, "What's happening in the markets today?")
        conversation_service.log_message(user.id, "user", prompt, input_type="text")
        history = conversation_service.get_recent_history(user.id)[:-1]
        try:
            reply = await asyncio.to_thread(
                claude_client.generate_reply, user.id, user.profile(), history, prompt
            )
        except Exception as exc:
            logger.warning("quick:%s AI generation failed: %s. Using smart fallback.", action, exc)
            from app.ai.llm_client import _smart_fallback_response
            reply = _smart_fallback_response(prompt, user.id)

        reply = trim_for_telegram(reply)
        conversation_service.log_message(user.id, "assistant", reply)
        for chunk in chunk_for_telegram(reply):
            await query.message.reply_text(chunk, reply_markup=_build_followup_keyboard("market"), parse_mode="Markdown")
        return

    # ── Competitor Comparison action ──
    if data.startswith("comp:"):
        ticker = data.split(":", 1)[1]
        await query.message.chat.send_action("typing")
        memory_service.touch_last_active(user.id)

        comps = market_data.get_competitors(ticker)
        comp_buttons = []
        for c in comps:
            comp_buttons.append([InlineKeyboardButton(f"🔍 Research {c['name']} ({c['ticker']})", callback_data=f"research:{c['ticker']}")])

        comp_buttons.append([InlineKeyboardButton("💡 Why Profitability Differs", callback_data=f"action:why_differs:{ticker}")])
        comp_buttons.append([InlineKeyboardButton("⚠️ Key Risk Factors", callback_data=f"action:risk:{ticker}")])

        comp_names = "\n".join([f"• **{c['name']}** ({c['ticker']})" for c in comps])
        msg = f"""🏢 **Competitor Research: {ticker}**

Top industry peers:
{comp_names}

❓ **Would you like to understand why their profitability differs?**"""
        await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(comp_buttons), parse_mode="Markdown")
        return

    # ── AI Research Score action ──
    if data.startswith("score:"):
        ticker = data.split(":", 1)[1]
        await query.message.chat.send_action("typing")
        memory_service.touch_last_active(user.id)

        hs = market_data.calculate_health_score(ticker)
        factors = hs.get("factors", {})
        factor_lines = "\n".join([f"• **{k}**: {v}" for k, v in factors.items()])

        msg = f"""⭐ **AI Research Score: {hs.get('name')} ({ticker})**

🏆 **Overall Score:** `{hs.get('overall_score')}/10`

📊 **5-Factor Breakdown:**
{factor_lines}

💡 **Why this score?**
{hs.get('score_justification')}

⚠️ *Disclaimer:* {hs.get('disclaimer')}"""
        await query.message.reply_text(msg, parse_mode="Markdown")
        return

    # ── Direct competitor / company research selection ──
    if data.startswith("research:"):
        target = data.split(":", 1)[1]
        await query.message.chat.send_action("typing")
        memory_service.touch_last_active(user.id)

        prompt = f"Give me full research and financials on {target}."
        conversation_service.log_message(user.id, "user", prompt, input_type="text")
        history = conversation_service.get_recent_history(user.id)[:-1]
        try:
            reply = await asyncio.to_thread(
                claude_client.generate_reply, user.id, user.profile(), history, prompt
            )
        except Exception as exc:
            logger.warning("research:%s AI generation failed: %s. Using smart fallback.", target, exc)
            from app.ai.llm_client import _smart_fallback_response
            reply = _smart_fallback_response(prompt, user.id)

        reply = trim_for_telegram(reply)
        conversation_service.log_message(user.id, "assistant", reply)
        for chunk in chunk_for_telegram(reply):
            await query.message.reply_text(chunk, reply_markup=_build_followup_keyboard(ticker=target), parse_mode="Markdown")
        return

    # ── Explain/Deepen & Guided Research actions ──
    if data.startswith("action:"):
        parts = data.split(":", 2)
        action_type = parts[1] if len(parts) > 1 else ""
        context_hint = parts[2] if len(parts) > 2 else ""

        await query.message.chat.send_action("typing")
        memory_service.touch_last_active(user.id)

        original_text = query.message.text or ""
        ticker = context_hint or "TATAMOTORS.NS"

        action_prompts = {
            "explain_simply": f"Take your previous response and re-explain it in the simplest possible way, like I'm completely new to finance. Use everyday analogies. Here's what you said:\n\n{original_text[:500]}",
            "tell_more": f"Expand on your previous response with more details, additional context, and deeper analysis. Here's what you said:\n\n{original_text[:500]}",
            "why_matters": f"Explain WHY the information in your previous response actually matters to an everyday investor. What should they pay attention to and what decisions could this inform? Here's what you said:\n\n{original_text[:500]}",
            "go_deeper": f"Provide an advanced, technical deep-dive on your previous response. Include specific metrics, ratios, comparisons, and technical analysis. Here's what you said:\n\n{original_text[:500]}",
            "profit_loss": f"Show 5-year historical revenue, net profit, profit margins, and key milestone turning points for {ticker}.",
            "why_differs": f"Explain why the profitability, business model, and profit margins of {ticker} differ from its main competitors.",
            "risk": f"What are the key risk factors, market vulnerabilities, beta volatility, and drawbacks for {ticker}?",
            "full_research": f"Give me full comprehensive research report on {ticker} covering business overview, financials, valuation, and outlook.",
            "stock": f"What is the current stock quote, 52-week range, day change, and analyst target price for {ticker}?",
            "news": f"What are the latest high-impact news developments and market events for {ticker}?",
        }

        prompt = action_prompts.get(action_type, f"Tell me more about: {original_text[:200]}")
        conversation_service.log_message(user.id, "user", f"[{action_type}]", input_type="text")
        try:
            reply = await asyncio.to_thread(
                claude_client.generate_reply, user.id, user.profile(), history, prompt
            )
        except Exception as exc:
            logger.warning("action:%s AI generation failed: %s. Using smart fallback.", action_type, exc)
            from app.ai.llm_client import _smart_fallback_response
            reply = _smart_fallback_response(prompt, user.id)
        reply = trim_for_telegram(reply)

        # Guided Next-Step Question & Keyboard
        if action_type == "profit_loss":
            guided_suffix = f"\n\n❓ **Would you like to compare {ticker} with its competitors?**"
            guided_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"⚖️ Compare {ticker} Competitors", callback_data=f"comp:{ticker}")],
                [InlineKeyboardButton("💡 Why Profitability Differs", callback_data=f"action:why_differs:{ticker}")],
                [InlineKeyboardButton("⭐ AI Health Score", callback_data=f"score:{ticker}")],
            ])
        elif action_type == "why_differs":
            guided_suffix = f"\n\n❓ **Would you like to examine key risk factors or take a quick lesson on Margin Analysis?**"
            guided_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚠️ Key Risk Factors", callback_data=f"action:risk:{ticker}")],
                [InlineKeyboardButton("🎓 Margin Analysis Lesson", callback_data="learn:revenue_profit")],
            ])
        else:
            guided_suffix = ""
            guided_kb = _build_followup_keyboard(context_hint, ticker=ticker)

        full_reply = reply + guided_suffix
        conversation_service.log_message(user.id, "assistant", full_reply)
        for chunk in chunk_for_telegram(full_reply):
            await query.message.reply_text(chunk, reply_markup=guided_kb, parse_mode="Markdown")
        return


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _handle_text_message(update, update.message.text, input_type="text")


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update)
    await update.message.chat.send_action("typing")
    tg_file = await update.message.voice.get_file()
    import tempfile
    local_path = os.path.join(tempfile.gettempdir(), f"voice_{user.telegram_id}_{update.message.message_id}.ogg")
    await tg_file.download_to_drive(local_path)

    try:
        text = await asyncio.to_thread(voice_service.transcribe, local_path)
    except Exception as exc:
        await update.message.reply_text(str(exc))
        return
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)

    await _handle_text_message(update, text, input_type="voice")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update)
    await update.message.chat.send_action("typing")

    photo = update.message.photo[-1]  # highest resolution
    tg_file = await photo.get_file()
    raw_bytes = bytes(await tg_file.download_as_bytearray())
    b64_image = base64.b64encode(raw_bytes).decode("utf-8")
    caption = update.message.caption or ""

    conversation_service.log_message(user.id, "user", caption or "[sent an image]", input_type="image")
    history = conversation_service.get_recent_history(user.id)[:-1]

    reply = await asyncio.to_thread(
        claude_client.analyze_image, user.id, user.profile(), history, b64_image, "image/jpeg", caption
    )
    reply = trim_for_telegram(reply)
    conversation_service.log_message(user.id, "assistant", reply)
    await update.message.reply_text(reply)


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update)
    await update.message.chat.send_action("typing")

    tg_doc = update.message.document
    tg_file = await tg_doc.get_file()
    raw_bytes = bytes(await tg_file.download_as_bytearray())

    file_path = document_service.save_uploaded_file(raw_bytes, tg_doc.file_name, user.id)
    extracted_text = await asyncio.to_thread(document_service.extract_text, file_path)

    if not extracted_text.strip():
        await update.message.reply_text(
            "I couldn't pull readable text out of that file — could be a scanned/image-only PDF. "
            "Try a text-based export if you have one."
        )
        return

    summary = await asyncio.to_thread(claude_client.summarize_document, extracted_text, tg_doc.file_name)

    from app.database import get_session
    from app.models.document import Document
    with get_session() as session:
        session.add(
            Document(
                user_id=user.id,
                filename=tg_doc.file_name,
                file_path=file_path,
                doc_type="pdf" if file_path.lower().endswith(".pdf") else "text",
                extracted_text=extracted_text,
                summary=summary,
            )
        )

    reply = f"Here's the rundown on {tg_doc.file_name}:\n\n{summary}\n\nAsk me anything else about it."
    conversation_service.log_message(user.id, "user", f"[uploaded document: {tg_doc.file_name}]", input_type="document")
    conversation_service.log_message(user.id, "assistant", reply)

    for chunk in chunk_for_telegram(reply):
        await update.message.reply_text(chunk)


def _detect_financial_response(text: str) -> bool:
    """Heuristic: does the reply contain financial data worth adding buttons to?"""
    financial_signals = ["₹", "P/E", "margin", "revenue", "market cap", "profit",
                         "NIFTY", "SENSEX", "valuation", "earnings", "stock", "sector"]
    return sum(1 for s in financial_signals if s.lower() in text.lower()) >= 2


async def _handle_text_message(update: Update, text: str, input_type: str):
    user = _get_user(update)
    await update.message.chat.send_action("typing")
    memory_service.touch_last_active(user.id)

    conversation_service.log_message(user.id, "user", text, input_type=input_type)

    # Check for "learn finance" trigger
    text_lower = text.strip().lower()
    if text_lower in ("learn", "learn finance", "teach me", "finance course", "learn investing"):
        await update.message.reply_text(
            "🎓 **Learn Finance** — Pick a topic to start learning!\n\n"
            "Topics are ordered from beginner to advanced. "
            "Take them in order, or jump to anything that interests you:",
            reply_markup=_build_learn_keyboard(),
            parse_mode="Markdown"
        )
        return

    # Check for "my preferences" / "settings" trigger
    if text_lower in ("my preferences", "preferences", "settings", "my settings", "my profile"):
        profile = user.profile()
        exp = profile.get("experience_level", "Not set")
        lang = profile.get("preferred_language", "Not set")
        style = profile.get("explanation_style", "Not set")
        markets = ", ".join(profile.get("markets", [])) or "Not set"
        interests = ", ".join(profile.get("interests", [])) or "Not set"
        freq = profile.get("update_frequency", "Not set")

        msg = f"""⚙️ **Your Preferences**

👤 Name: {user.first_name or 'Not set'}
📊 Experience: {exp}
🌐 Language: {lang}
📝 Explanation style: {style}
🗺️ Markets: {markets}
💡 Interests: {interests}
🔔 Update frequency: {freq}

_To change any preference, just tell me naturally — e.g. "change my language to Hinglish" or "I'm an advanced investor now"_"""
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    if user.onboarding_stage != "done":
        reply, completed = await onboarding.handle_onboarding_turn(user, text)
        conversation_service.log_message(user.id, "assistant", reply)
        await update.message.reply_text(trim_for_telegram(reply))
        if completed:
            logger.info("User %s completed onboarding", user.telegram_id)
        return

    history = conversation_service.get_recent_history(user.id)[:-1]  # exclude the message we just logged
    try:
        reply = await asyncio.to_thread(
            claude_client.generate_reply, user.id, user.profile(), history, text
        )
    except Exception as exc:
        logger.warning("generate_reply failed for user %s: %s. Using smart fallback.", user.id, exc)
        from app.ai.llm_client import _smart_fallback_response
        reply = _smart_fallback_response(text, user.id)

    reply = trim_for_telegram(reply)
    conversation_service.log_message(user.id, "assistant", reply)

    # Add interactive buttons if response contains financial metrics
    keyboard = _build_followup_keyboard() if _detect_financial_response(reply) else None
    chunks = chunk_for_telegram(reply)

    for i, chunk in enumerate(chunks):
        # Attach keyboard to the final chunk
        if i == len(chunks) - 1 and keyboard:
            await update.message.reply_text(chunk, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await update.message.reply_text(chunk, parse_mode="Markdown")
