"""
Entry point. Boots the database, starts the Telegram bot in polling mode,
and schedules the proactive intelligence jobs (daily briefings, watchlist
alerts, reminders) via APScheduler running inside the same asyncio loop.
"""
import logging
import asyncio

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import init_db
from app.bot import handlers
from app.scheduler import jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


from telegram.request import HTTPXRequest


def build_application():
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).request(request).build()

    # /start is the one unavoidable Telegram-native trigger to open a chat;
    # everything after it is natural conversation, no other commands exist.
    application.add_handler(CommandHandler("start", handlers.start_handler))

    # Inline keyboard button presses (Learn Finance, Explain Simply, etc.)
    application.add_handler(CallbackQueryHandler(handlers.callback_handler))

    application.add_handler(MessageHandler(filters.VOICE, handlers.voice_handler))
    application.add_handler(MessageHandler(filters.PHOTO, handlers.photo_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, handlers.document_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_handler))

    return application


async def _post_init(application):
    scheduler = AsyncIOScheduler()
    bot = application.bot
    scheduler.add_job(jobs.send_daily_briefings, "interval", minutes=15, args=[bot])
    scheduler.add_job(jobs.send_evening_summaries, "interval", minutes=30, args=[bot])
    scheduler.add_job(jobs.check_watchlist_alerts, "interval", minutes=10, args=[bot])
    scheduler.add_job(jobs.deliver_scheduled_reminders, "interval", minutes=1, args=[bot])
    scheduler.add_job(jobs.proactive_insight_scan, "interval", hours=2, args=[bot])
    scheduler.start()
    logger.info("Scheduler started: briefings, evening summaries, watchlist alerts, reminders, proactive insights.")


def main():
    if not settings.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your .env before running. See .env.example.")

    init_db()
    application = build_application()
    application.post_init = _post_init

    logger.info("Financial Assistant bot starting (polling mode)...")
    while True:
        try:
            application.run_polling(allowed_updates=["message", "callback_query"])
            break
        except Exception as exc:
            logger.warning("Polling connection issue (%s). Retrying in 3 seconds...", exc)
            import time
            time.sleep(3)


if __name__ == "__main__":
    main()
