"""
Transcribes Telegram voice notes (OGG/Opus) to text.
Supports OpenAI Whisper API when key is configured, with SpeechRecognition
free Web Speech API fallback when unconfigured.
"""
import os
import logging
from app.config import settings

logger = logging.getLogger(__name__)


def transcribe(file_path: str) -> str:
    # 1. Try OpenAI Whisper if key is present
    if settings.OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            with open(file_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
            if transcript.text:
                return transcript.text
        except Exception as exc:
            logger.warning("OpenAI Whisper transcription failed: %s. Trying SpeechRecognition fallback.", exc)

    # 2. Try SpeechRecognition free Web Speech API fallback
    try:
        import speech_recognition as sr
        from pydub import AudioSegment

        # Configure static ffmpeg binary from imageio_ffmpeg if installed
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
            return text.strip()
    except Exception as exc:
        logger.warning("SpeechRecognition fallback failed or audio decoder unavailable: %s", exc)

    # 3. Informative notice if transcription could not process audio
    raise RuntimeError(
        "Voice transcription is unconfigured (no OPENAI_API_KEY). "
        "Text and photo messages work great!"
    )
