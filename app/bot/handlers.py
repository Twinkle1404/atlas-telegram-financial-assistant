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
from app.services import memory_service, conversation_service, document_service
from app.services import market_data, voice_service
from app.utils.formatting import trim_for_telegram, chunk_for_telegram

logger = logging.getLogger(__name__)

# ── Learn Finance progressive curriculum ──
LEARN_TOPICS = [
    ("stock_basics", "📈 What is a Stock?", "Explain what a stock is, why companies issue stocks, and how everyday people can own a piece of a company. Use simple language with real examples."),
    ("stock_market", "🏛️ How the Stock Market Works", "Explain how stock markets (like NSE, BSE, NYSE) work — how buying and selling happens, what determines prices, and why markets go up and down. Keep it simple and beginner-friendly."),
    ("index", "📊 What is NIFTY 50 / SENSEX?", "Explain what stock market indices are, specifically NIFTY 50 and SENSEX. Why do people track them? What does it mean when NIFTY goes up or down? Use simple analogies."),
    ("revenue_profit", "💰 Revenue & Profit Explained", "Explain the difference between revenue and profit. Use a simple example like a chai shop to explain revenue, costs, gross profit, and net profit."),
    ("pe_eps", "🔢 P/E Ratio & EPS", "Explain P/E ratio and EPS (Earnings Per Share) in the simplest way possible. Use a real company example. Explain what a 'high P/E' vs 'low P/E' means and why it matters."),
    ("financial_statements", "📋 Reading Financial Statements", "Explain the 3 main financial statements: Income Statement, Balance Sheet, and Cash Flow Statement. What does each one tell you? Keep it simple with analogies."),
    ("roe_roce", "📐 ROE & ROCE", "Explain Return on Equity (ROE) and Return on Capital Employed (ROCE). Why do investors care about these numbers? Use simple examples."),
    ("valuation", "💎 Company Valuation Basics", "Explain how to tell if a stock is 'expensive' or 'cheap'. Cover P/E, P/B, and market cap. Explain why a ₹100 stock can be more expensive than a ₹2000 stock."),
    ("diversification", "🛡️ Diversification & Risk", "Explain portfolio diversification — why you shouldn't put all your money in one stock. Explain different types of risk (market risk, company risk, sector risk)."),
    ("mutual_funds", "🏦 Mutual Funds & ETFs", "Explain what mutual funds and ETFs are, how they differ from buying individual stocks, and why beginners often start with them. Keep it very simple."),
]


def _build_learn_keyboard() -> InlineKeyboardMarkup:
    """Builds the Learn Finance topic selection keyboard."""
    buttons = []
    for topic_id, topic_name, _ in LEARN_TOPICS:
        buttons.append([InlineKeyboardButton(topic_name, callback_data=f"learn:{topic_id}")])
    return InlineKeyboardMarkup(buttons)


def _build_followup_keyboard(context_hint: str = "") -> InlineKeyboardMarkup:
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


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update)
    if user.onboarding_stage == "done":
        msg = await asyncio.to_thread(_build_welcome_back, user)
        # Add quick action buttons for returning users
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📈 Market Update", callback_data="quick:market"),
                InlineKeyboardButton("📰 Today's News", callback_data="quick:news"),
            ],
            [
                InlineKeyboardButton("🎓 Learn Finance", callback_data="quick:learn"),
                InlineKeyboardButton("⚙️ My Preferences", callback_data="quick:preferences"),
            ],
        ])
        await update.message.reply_text(msg, reply_markup=keyboard)
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

    # ── Quick actions ──
    if data.startswith("quick:"):
        action = data.split(":", 1)[1]
        await query.message.chat.send_action("typing")
        memory_service.touch_last_active(user.id)

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

        # Market update or news — route through AI
        prompts_map = {
            "market": "Give me a quick market update for today — key indices, what moved and why.",
            "news": "What are the most important financial news stories today? Pick the 2-3 that actually matter and explain why.",
        }
        prompt = prompts_map.get(action, "What's happening in the markets today?")
        conversation_service.log_message(user.id, "user", prompt, input_type="text")
        history = conversation_service.get_recent_history(user.id)[:-1]
        reply = await asyncio.to_thread(
            claude_client.generate_reply, user.id, user.profile(), history, prompt
        )
        reply = trim_for_telegram(reply)
        conversation_service.log_message(user.id, "assistant", reply)
        for chunk in chunk_for_telegram(reply):
            await query.message.reply_text(chunk, reply_markup=_build_followup_keyboard("market"))
        return

    # ── Explain/Deepen actions ──
    if data.startswith("action:"):
        parts = data.split(":", 2)
        action_type = parts[1] if len(parts) > 1 else ""
        context_hint = parts[2] if len(parts) > 2 else ""

        await query.message.chat.send_action("typing")
        memory_service.touch_last_active(user.id)

        # Get the message that the button was attached to as context
        original_text = query.message.text or ""
        action_prompts = {
            "explain_simply": f"Take your previous response and re-explain it in the simplest possible way, like I'm completely new to finance. Use everyday analogies. Here's what you said:\n\n{original_text[:500]}",
            "tell_more": f"Expand on your previous response with more details, additional context, and deeper analysis. Here's what you said:\n\n{original_text[:500]}",
            "why_matters": f"Explain WHY the information in your previous response actually matters to an everyday investor. What should they pay attention to and what decisions could this inform? Here's what you said:\n\n{original_text[:500]}",
            "go_deeper": f"Provide an advanced, technical deep-dive on your previous response. Include specific metrics, ratios, comparisons, and technical analysis. Here's what you said:\n\n{original_text[:500]}",
        }

        prompt = action_prompts.get(action_type, f"Tell me more about: {original_text[:200]}")
        conversation_service.log_message(user.id, "user", f"[{action_type}]", input_type="text")
        history = conversation_service.get_recent_history(user.id)[:-1]
        reply = await asyncio.to_thread(
            claude_client.generate_reply, user.id, user.profile(), history, prompt
        )
        reply = trim_for_telegram(reply)
        conversation_service.log_message(user.id, "assistant", reply)
        for chunk in chunk_for_telegram(reply):
            await query.message.reply_text(chunk, reply_markup=_build_followup_keyboard(context_hint))
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
    reply = await asyncio.to_thread(
        claude_client.generate_reply, user.id, user.profile(), history, text
    )
    reply = trim_for_telegram(reply)
    conversation_service.log_message(user.id, "assistant", reply)

    # Add interactive buttons if the response contains financial data
    keyboard = _build_followup_keyboard() if _detect_financial_response(reply) else None

    for chunk in chunk_for_telegram(reply):
        # Only attach keyboard to the last chunk
        if chunk == chunk_for_telegram(reply)[-1] and keyboard:
            await update.message.reply_text(chunk, reply_markup=keyboard)
        else:
            await update.message.reply_text(chunk)
