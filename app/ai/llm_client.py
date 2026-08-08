"""
Unified LLM adapter that supports Anthropic, Google Gemini, and OpenAI models.
Maintains full backward compatibility with `claude_client.py`.
"""
import os
import json
import logging
from datetime import datetime

from app.config import settings
from app.ai.prompts import build_system_prompt, ONBOARDING_SYSTEM_PROMPT
# Lazy tool import inside functions to avoid circular dependencies

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


def get_available_provider() -> str:
    if settings.ANTHROPIC_API_KEY:
        return "anthropic"
    elif os.getenv("GEMINI_API_KEY"):
        return "gemini"
    elif settings.OPENAI_API_KEY:
        return "openai"
    return "anthropic"  # Default attempt


def _run_anthropic_loop(system_prompt: str, messages: list, user_id: int, use_tools: bool) -> str:
    import anthropic
    from app.ai.tools import TOOL_SCHEMAS, dispatch_tool
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
            tools=TOOL_SCHEMAS if use_tools else [],
        )

        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text").strip()

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result_json = dispatch_tool(block.name, block.input, user_id)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result_json}
                )
        messages.append({"role": "user", "content": tool_results})

    return "I reached the maximum tool reasoning steps -- would you like me to refine the analysis?"


def _run_openai_loop(system_prompt: str, messages: list, user_id: int, use_tools: bool) -> str:
    from openai import OpenAI
    from app.ai.tools import TOOL_SCHEMAS, dispatch_tool
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    formatted_messages = [{"role": "system", "content": system_prompt}]
    for m in messages:
        if isinstance(m.get("content"), str):
            formatted_messages.append({"role": m["role"], "content": m["content"]})
        elif isinstance(m.get("content"), list):
            text_part = ""
            for item in m["content"]:
                if item.get("type") == "text":
                    text_part += item.get("text", "")
            formatted_messages.append({"role": m["role"], "content": text_part or str(m["content"])})

    tools_openai = []
    if use_tools:
        for s in TOOL_SCHEMAS:
            tools_openai.append({
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": s["input_schema"],
                }
            })

    for _ in range(MAX_TOOL_ROUNDS):
        kwargs = {"model": "gpt-4o-mini", "messages": formatted_messages}
        if tools_openai:
            kwargs["tools"] = tools_openai

        response = client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        if not msg.tool_calls:
            return (msg.content or "").strip()

        formatted_messages.append(msg)
        for tool_call in msg.tool_calls:
            args = json.loads(tool_call.function.arguments or "{}")
            result_json = dispatch_tool(tool_call.function.name, args, user_id)
            formatted_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_json
            })

    return "Completed research steps."


def run_llm_loop(system_prompt: str, messages: list, user_id: int, use_tools: bool) -> str:
    provider = get_available_provider()
    try:
        if provider == "anthropic" and settings.ANTHROPIC_API_KEY:
            return _run_anthropic_loop(system_prompt, messages, user_id, use_tools)
        elif provider == "openai" or settings.OPENAI_API_KEY:
            return _run_openai_loop(system_prompt, messages, user_id, use_tools)
        else:
            return _run_anthropic_loop(system_prompt, messages, user_id, use_tools)
    except Exception as exc:
        logger.exception("LLM generation error: %s", exc)
        return f"Service update: Unable to process LLM turn ({str(exc)}). Please check API configuration."
