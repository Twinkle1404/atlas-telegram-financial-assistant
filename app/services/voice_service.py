"""
Transcribes Telegram voice notes (OGG/Opus) to text.

Multi-engine pipeline (tries each in order, stops at first success):
  1. Groq Whisper API  – free tier, supports OGG natively, no ffmpeg needed
  2. OpenAI Whisper API – requires OPENAI_API_KEY
  3. SpeechRecognition  – Google Web Speech via pydub (needs ffmpeg for OGG→WAV)

Set GROQ_API_KEY in .env for the recommended zero-cost engine.
"""
import os
import logging
from app.config import settings

logger = logging.getLogger(__name__)


def transcribe(file_path: str) -> str:
    """Try each engine in order; return transcribed text or raise RuntimeError."""
    errors = []

    # ── Engine 1: Groq Whisper (free, OGG native) ──
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            with open(file_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    file=(os.path.basename(file_path), f.read()),
                    model="whisper-large-v3-turbo",
                    language="en",
                    temperature=0.0,
                )
            if result.text and result.text.strip():
                logger.info("Voice transcribed via Groq Whisper (%d chars)", len(result.text))
                return result.text.strip()
        except Exception as exc:
            errors.append(f"Groq Whisper: {exc}")
            logger.warning("Groq Whisper failed: %s", exc)

    # ── Engine 2: OpenAI Whisper ──
    if settings.OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            with open(file_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file
                )
            if transcript.text and transcript.text.strip():
                logger.info("Voice transcribed via OpenAI Whisper (%d chars)", len(transcript.text))
                return transcript.text.strip()
        except Exception as exc:
            errors.append(f"OpenAI Whisper: {exc}")
            logger.warning("OpenAI Whisper failed: %s. Trying next engine.", exc)

    # ── Engine 3: SpeechRecognition + pydub (needs ffmpeg for OGG→WAV) ──
    try:
        import speech_recognition as sr
        from pydub import AudioSegment

        # Try imageio_ffmpeg bundled binary if system ffmpeg is missing
        try:
            import imageio_ffmpeg
            AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass

        wav_path = file_path + ".wav"
        audio = AudioSegment.from_file(file_path)
        audio.export(wav_path, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)

        if os.path.exists(wav_path):
            os.remove(wav_path)

        if text and text.strip():
            logger.info("Voice transcribed via SpeechRecognition (%d chars)", len(text))
            return text.strip()
    except Exception as exc:
        errors.append(f"SpeechRecognition: {exc}")
        logger.warning("SpeechRecognition fallback failed: %s", exc)

    # ── All engines exhausted ──
    detail = "; ".join(errors) if errors else "No transcription engine configured"
    logger.error("All voice transcription engines failed: %s", detail)
    raise RuntimeError(
        "🎙️ Voice transcription isn't available right now.\n\n"
        "To enable it, add a free GROQ_API_KEY to your .env file "
        "(get one at console.groq.com — no credit card needed).\n\n"
        "In the meantime, text and photo messages work great! "
        "Try typing your question instead. 💬"
    )
