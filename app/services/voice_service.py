"""
Transcribes Telegram voice notes (OGG/Opus) to text. Uses OpenAI's Whisper
API when a key is configured. Without a key, raises a clear error so the
bot can tell the user voice isn't set up yet, rather than failing silently.
"""
import os
from app.config import settings


def transcribe(file_path: str) -> str:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError(
            "Voice transcription isn't configured yet (no OPENAI_API_KEY). "
            "Text and images still work great."
        )
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
    return transcript.text
