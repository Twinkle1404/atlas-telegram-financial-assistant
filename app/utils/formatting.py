"""Small helpers to keep replies scannable on a phone screen."""
from app.config import settings


def trim_for_telegram(text: str, limit: int = None) -> str:
    limit = limit or settings.MAX_RESPONSE_CHARS
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(". ", 1)[0]
    return cut + "…"


def chunk_for_telegram(text: str, chunk_size: int = 4000) -> list[str]:
    """Telegram hard-caps messages at 4096 chars; split long doc summaries safely."""
    if len(text) <= chunk_size:
        return [text]
    chunks, current = [], []
    length = 0
    for paragraph in text.split("\n"):
        if length + len(paragraph) + 1 > chunk_size:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(paragraph)
        length += len(paragraph) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
