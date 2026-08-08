"""
Onboarding is just a specially-prompted conversation (see
ai/prompts.py::ONBOARDING_SYSTEM_PROMPT), not a rigid form. We track it as a
stage on the User row: "new" -> first message triggers a welcome + first
question -> "in_progress" while Claude naturally gathers context -> "done"
once the user signals they're ready to move on (or after a few exchanges),
at which point we distill the transcript into a structured profile.
"""
from app.ai import claude_client
from app.services import memory_service, conversation_service

# Heuristic cap so onboarding can't loop forever if the user just keeps chatting
MAX_ONBOARDING_TURNS = 6

_DONE_SIGNALS = ("skip", "let's start", "lets start", "just start", "later", "no thanks")


async def handle_onboarding_turn(user, text: str) -> tuple[str, bool]:
    """Returns (reply_text, onboarding_just_completed).
    Assumes the caller has already logged `text` as the latest user message,
    so we fetch history and drop that trailing duplicate before re-adding it."""
    history = conversation_service.get_recent_history(user.id, limit=13)[:-1]

    reply = claude_client.generate_onboarding_reply(history, text)

    turns_so_far = len([m for m in history if m["role"] == "user"]) + 1
    should_wrap_up = turns_so_far >= MAX_ONBOARDING_TURNS or any(
        s in text.lower() for s in _DONE_SIGNALS
    )

    if should_wrap_up:
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history) + f"\nuser: {text}"
        profile = claude_client.extract_onboarding_profile(transcript)
        if profile:
            memory_service.update_profile(user.id, profile)
        memory_service.mark_onboarded(user.id, profile.get("briefing_hour_local"))
        return reply, True

    return reply, False


def welcome_message(first_name: str) -> str:
    name = f", {first_name}" if first_name else ""
    return (
        f"Hey{name} — I'm your financial assistant. Think of me less like a bot and "
        "more like an analyst on call: I track markets, research companies, read "
        "filings and reports, and keep you briefed on what actually matters.\n\n"
        "No forms to fill out — just talk to me. To get useful fast, mind telling me "
        "a bit about what you do and what you're watching? (Totally skippable — just "
        "say so and we can dive straight in.)"
    )
