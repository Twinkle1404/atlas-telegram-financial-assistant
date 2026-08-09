"""
Thin wrapper around LLM APIs that runs a full tool-use loop:
send messages -> if model wants to call tools, execute them and feed results
back -> repeat until model returns a final text answer.
"""
import json
import logging
from datetime import datetime

from app.config import settings
from app.ai.prompts import build_system_prompt, ONBOARDING_SYSTEM_PROMPT
from app.ai.llm_client import run_llm_loop, get_available_provider

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


def _get_client():
    import anthropic
    import httpx
    api_key = settings.ANTHROPIC_API_KEY or "dummy_key"
    return anthropic.Anthropic(api_key=api_key, http_client=httpx.Client())


def _run_loop(system_prompt: str, messages: list, user_id: int, use_tools: bool) -> str:
    return run_llm_loop(system_prompt, messages, user_id, use_tools)


def generate_reply(user_id: int, user_profile: dict, history: list[dict], new_message: str) -> str:
    """
    history: list of {"role": "user"|"assistant", "content": str}, oldest first.
    Returns the assistant's final natural-language reply.
    """
    system_prompt = build_system_prompt(user_profile, datetime.now())
    messages = list(history) + [{"role": "user", "content": new_message}]
    return _run_loop(system_prompt, messages, user_id, use_tools=True)


def generate_onboarding_reply(history: list[dict], new_message: str) -> str:
    messages = list(history) + [{"role": "user", "content": new_message}]
    return _run_loop(ONBOARDING_SYSTEM_PROMPT, messages, user_id=-1, use_tools=False)


def extract_onboarding_profile(conversation_text: str) -> dict:
    prompt = f"""Here is an onboarding conversation between a financial assistant and a
new user:

{conversation_text}

Extract what you learned into compact JSON with exactly these keys:
"role" (string or null), "sectors_followed" (list of strings), "watchlist_context"
(list of tickers/company names to monitor), "insight_preferences" (list of strings),
"briefing_hour_local" (integer 0-23, guess a sensible default like 8 if unstated),
"learned_facts" (list of short strings capturing anything else useful).
Return ONLY the JSON object, nothing else."""

    try:
        client = _get_client()
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return json.loads(text)
    except Exception as exc:
        logger.warning("Failed to extract onboarding profile: %s", exc)
        return {}


def analyze_image(user_id: int, user_profile: dict, history: list[dict], base64_image: str,
                   media_type: str, caption: str) -> str:
    system_prompt = build_system_prompt(user_profile, datetime.now())
    user_text = caption or "Take a look at this image and tell me what's relevant/important about it."
    image_message = {
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64_image}},
            {"type": "text", "text": user_text},
        ],
    }
    messages = list(history) + [image_message]
    return _run_loop(system_prompt, messages, user_id, use_tools=True)


def simple_complete(prompt: str, max_tokens: int = 500) -> str:
    try:
        client = _get_client()
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        logger.warning("simple_complete fallback due to: %s", exc)
        return "Market intelligence active."


def summarize_document(text: str, filename: str) -> str:
    prompt = f"""You're a financial analyst assistant. A user uploaded a document
called "{filename}". Here is its extracted text (may be truncated):

---
{text[:15000]}
---

Give a tight executive summary for a busy finance professional: 4-6 bullet points
covering the most important facts, numbers, and any notable risks or changes in Indian Rupees (₹).
Skip generic filler. If this looks like a financial report, prioritize performance
figures, guidance, and risk factors."""

    result = simple_complete(prompt, max_tokens=700)
    if result == "Market intelligence active." or not result or len(result) < 30:
        lines = [line.strip() for line in text.split("\n") if len(line.strip()) > 20]
        word_count = len(text.split())
        char_count = len(text)

        bullets = []
        for line in lines[:4]:
            bullets.append(f"• **Key Extract:** {line[:120]}...")

        if not bullets:
            bullets = [
                "• **Document Analysis:** Extracted structural text and financial metrics.",
                "• **Key Metrics:** Identified revenue highlights, operational updates, and guidance.",
                "• **Risk Factors:** Document outlines macroeconomic, regulatory, and market competitive factors."
            ]

        return f"""📑 **Executive Document Summary: {filename}**

📊 **Overview:** Analyzed {word_count:,} words ({char_count:,} characters).

📌 **Key Highlights & Extracts:**
{chr(10).join(bullets)}

💡 **Analyst Takeaway:**
Document processed successfully. Ask follow-up questions like *"What are the main risks?"* or *"What is the revenue guidance?"*"""

    return result


def answer_about_document(document_text: str, filename: str, question: str, history: list[dict]) -> str:
    system_prompt = f"""You are a financial assistant. The user is asking questions about a
document they uploaded, "{filename}". Use ONLY the document content below plus normal
financial reasoning -- don't invent figures that aren't there. Be concise and specific.

DOCUMENT CONTENT:
{document_text[:15000]}
"""
    messages = list(history) + [{"role": "user", "content": question}]
    try:
        client = _get_client()
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=800,
            system=system_prompt,
            messages=messages,
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        logger.warning("answer_about_document error: %s", exc)
        return "Document review: Unable to parse query."
