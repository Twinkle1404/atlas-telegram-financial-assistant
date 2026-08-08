"""
Proactive intelligence lives here. Three jobs, all on the same principle
from the spec: silence is a valid, preferred output when nothing meaningful
happened -- these jobs actively decide whether to send anything at all.

NOTE on timezones: for prototype simplicity `briefing_hour_local` is compared
directly to the current UTC hour. A production version would store each
user's IANA timezone (captured during onboarding, e.g. via Telegram client
locale or an explicit question) and convert properly with `pytz`/`zoneinfo`.
"""
import logging
from datetime import datetime, date

from telegram import Bot

from app.database import get_session
from app.models.user import User
from app.models.watchlist import WatchlistItem, ScheduledEvent
from app.services import market_data, news_service
from app.ai import claude_client
from app.utils.formatting import chunk_for_telegram

logger = logging.getLogger(__name__)

# In-memory guard so a briefing only fires once per user per day within one process.
_last_briefing_date: dict[int, date] = {}


async def send_daily_briefings(bot: Bot):
    now = datetime.utcnow()
    with get_session() as session:
        users = session.query(User).filter_by(onboarding_stage="done", briefing_enabled=True).all()
        candidates = [
            (u.id, u.telegram_id, u.profile(), u.briefing_hour_local)
            for u in users
            if u.briefing_hour_local == now.hour and _last_briefing_date.get(u.id) != now.date()
        ]

    for user_id, telegram_id, profile, _hour in candidates:
        try:
            brief = _build_market_brief(profile)
            if brief:  # None/"" means "nothing worth sending"
                for chunk in chunk_for_telegram(brief):
                    await bot.send_message(chat_id=telegram_id, text=chunk)
            _last_briefing_date[user_id] = now.date()
        except Exception:
            logger.exception("Failed to send daily briefing to user %s", user_id)


def _build_market_brief(profile: dict) -> str:
    overview = market_data.get_market_overview()
    watchlist = profile.get("watchlist_context", [])
    watchlist_news = {t: news_service.get_company_news(t, 3) for t in watchlist[:5]}

    prompt = f"""Compose today's morning market briefing for this user.

Market overview: {overview}
News on their watchlist ({watchlist}): {watchlist_news}
Sectors they follow: {profile.get('sectors_followed')}

Write 3-6 tight bullet points covering only what's genuinely notable -- skip
anything routine. Explain *why* each item matters to someone with this
person's interests. If truly nothing notable happened, respond with exactly:
NOTHING_NOTABLE"""

    result = claude_client.simple_complete(prompt, max_tokens=500)
    if "NOTHING_NOTABLE" in result:
        return ""
    return "☀️ Morning brief\n\n" + result


async def check_watchlist_alerts(bot: Bot):
    """Polls watchlisted tickers for large intraday moves and fresh filings."""
    with get_session() as session:
        items = session.query(WatchlistItem).all()
        users_by_id = {u.id: u for u in session.query(User).all()}

        for item in items:
            try:
                quote = market_data.get_quote(item.ticker)
                change = quote.get("change_pct")
                threshold = item.move_pct_threshold or 5.0
                if change is not None and abs(change) >= threshold:
                    already_notified = item.last_known_price == quote.get("price")
                    if not already_notified:
                        user = users_by_id.get(item.user_id)
                        if user:
                            direction = "up" if change > 0 else "down"
                            msg = (
                                f"⚡ {item.ticker} is {direction} {abs(change):.1f}% today "
                                f"(now ${quote.get('price')}). You're tracking this because: "
                                f"{item.reason or 'it is on your watchlist'}."
                            )
                            await bot.send_message(chat_id=user.telegram_id, text=msg)
                        item.last_known_price = quote.get("price")
            except Exception:
                logger.exception("Watchlist check failed for %s", item.ticker)


async def send_evening_summaries(bot: Bot):
    now = datetime.utcnow()
    evening_hour = 17  # 5 PM local
    with get_session() as session:
        users = session.query(User).filter_by(onboarding_stage="done", briefing_enabled=True).all()
        candidates = [
            (u.id, u.telegram_id, u.profile())
            for u in users
            if now.hour == evening_hour
        ]

    for user_id, telegram_id, profile in candidates:
        try:
            overview = market_data.get_market_overview()
            prompt = f"""Compose today's evening market summary for this user.
Market overview: {overview}
Sectors: {profile.get('sectors_followed')}

Write 3 bullet points summarizing key index movements and market close drivers in Indian Rupees (₹).
If nothing notable, respond with: NOTHING_NOTABLE"""
            summary = claude_client.simple_complete(prompt, max_tokens=400)
            if "NOTHING_NOTABLE" not in summary:
                for chunk in chunk_for_telegram("🌙 Evening market summary\n\n" + summary):
                    await bot.send_message(chat_id=telegram_id, text=chunk)
        except Exception:
            logger.exception("Failed to send evening summary to user %s", user_id)


async def deliver_scheduled_reminders(bot: Bot):
    now = datetime.utcnow()
    with get_session() as session:
        due = (
            session.query(ScheduledEvent)
            .filter(ScheduledEvent.delivered.is_(False), ScheduledEvent.fire_at_utc <= now)
            .all()
        )
        users_by_id = {u.id: u for u in session.query(User).all()}
        for event in due:
            user = users_by_id.get(event.user_id)
            if user:
                try:
                    await bot.send_message(chat_id=user.telegram_id, text=f"⏰ Reminder: {event.description}")
                except Exception:
                    logger.exception("Failed to deliver reminder %s", event.id)
            event.delivered = True

