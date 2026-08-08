"""
Extracts text from uploaded financial documents so Claude can summarize/answer
questions about them. PDF is the primary case (reports, decks, filings);
plain text/CSV are read directly.
"""
import os
import pdfplumber

from app.config import settings


def save_uploaded_file(raw_bytes: bytes, filename: str, user_id: int) -> str:
    user_dir = os.path.join(settings.DOCUMENTS_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, filename)
    with open(path, "wb") as f:
        f.write(raw_bytes)
    return path


def extract_text(file_path: str) -> str:
    lower = file_path.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf_text(file_path)
    if lower.endswith((".txt", ".csv")):
        with open(file_path, "r", errors="ignore") as f:
            return f.read()
    return ""


def _extract_pdf_text(file_path: str, max_pages: int = 60) -> str:
    text_chunks = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages[:max_pages]:
            page_text = page.extract_text() or ""
            text_chunks.append(page_text)
    return "\n".join(text_chunks)
