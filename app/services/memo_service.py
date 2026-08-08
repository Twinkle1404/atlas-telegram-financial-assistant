"""
Investment Committee (IC) Research Memo Generator: compiles research findings,
filings, news, metrics, and comparisons into a professional Markdown IC One-Pager.
"""
import os
from datetime import datetime

from app.config import settings
from app.services import conversation_service, memory_service
from app.ai import claude_client


def export_research_memo(user_id: int, topic: str) -> dict:
    """
    Synthesizes current conversation context, quotes, filings, news, and fundamentals
    into an Investment Committee (IC) One-Pager Markdown document.
    Saves the file for downloadable export via Telegram.
    """
    user = memory_service.get_user_by_id(user_id)
    history = conversation_service.get_recent_history(user_id, limit=15)
    history_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)

    prompt = f"""You are a senior financial analyst preparing a formal Investment Committee (IC) One-Pager Research Memo.

Target Company / Topic: {topic}
User Profile Context: {user.profile() if user else {}}

Recent Research Conversation Transcript:
---
{history_text}
---

Generate a clean, high-impact Markdown Investment Committee (IC) One-Pager Memo.
Use this exact structure:

# INVESTMENT COMMITTEE RESEARCH MEMO: {topic.upper()}
**Date:** {datetime.now().strftime('%B %d, %Y')}
**Author:** AI Financial Analyst & Assistant

---

### 1. Executive Summary & Investment Thesis
- 2-3 concise bullet points stating the core investment thesis and why it matters.

### 2. Key Valuation & Financial Metrics (in ₹ / INR)
- Include Market Cap (₹ Cr), P/E ratio, Revenue Growth %, Profit Margins, and 52-week Range where discussed or relevant.

### 3. Key Growth Catalysts & Strategic Drivers
- Bulleted list of key revenue drivers, product launches, or market opportunities.

### 4. Key Investment Risks & Mitigation
- High-impact risk factors (regulatory, competitive, macro, execution).

### 5. Analyst Recommendation & Action Items
- Recommended position/action and follow-up monitoring items.

Format strictly in clean Github-flavored Markdown. Express all monetary amounts in Indian Rupees (₹ / INR)."""

    memo_content = claude_client.simple_complete(prompt, max_tokens=1000)

    # Save memo file
    output_dir = os.path.join(settings.DOCUMENTS_DIR, str(user_id), "memos")
    os.makedirs(output_dir, exist_ok=True)
    clean_topic = "".join(c for c in topic if c.isalnum() or c in ("_", "-")).strip() or "research"
    filename = f"IC_Memo_{clean_topic}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    file_path = os.path.join(output_dir, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(memo_content)

    return {
        "status": "exported",
        "filename": filename,
        "file_path": file_path,
        "memo_content": memo_content,
    }
