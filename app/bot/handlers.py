"""
All Telegram-facing logic. Deliberately command-free: /start is unavoidable
(Telegram requires some trigger to open a bot chat) and is treated purely as
"say hello", not a menu. Everything else -- text, voice, photos, documents --
flows through natural conversation handlers into the same AI pipeline.
"""
import asyncio
import base64
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from app.ai import claude_client
from app.bot import onboarding
from app.services import memory_service, conversation_service, document_service
from app.services import voice_service
from app.utils.formatting import trim_for_telegram, chunk_for_telegram

logger = logging.getLogger(__name__)


def _get_user(update: Update):
    tg_user = update.effective_user
    return memory_service.get_or_create_user(
        telegram_id=str(tg_user.id), first_name=tg_user.first_name or "", username=tg_user.username or ""
    )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update)
    if user.onboarding_stage == "done":
        await update.message.reply_text(
            f"Welcome back{', ' + user.first_name if user.first_name else ''}. "
            "What's on your mind — markets, a company, a document?"
        )
        return
    await update.message.reply_text(onboarding.welcome_message(user.first_name))
    conversation_service.log_message(user.id, "assistant", onboarding.welcome_message(user.first_name))


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


async def _handle_text_message(update: Update, text: str, input_type: str):
    user = _get_user(update)
    await update.message.chat.send_action("typing")
    memory_service.touch_last_active(user.id)

    conversation_service.log_message(user.id, "user", text, input_type=input_type)

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

    for chunk in chunk_for_telegram(reply):
        await update.message.reply_text(chunk)
