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
MAX_ONBOARDING_TURNS = 10

_DONE_SIGNALS = ("skip", "let's start", "lets start", "just start", "later",
                 "no thanks", "done", "start", "finish", "that's it", "thats it",
                 "move on", "let's go", "lets go", "enough", "all set")


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
    name = f" {first_name}" if first_name else ""
    return (
        f"Hey{name}! 👋 Welcome to Atlas — your personal AI financial assistant.\n\n"
        "I'm here to help you understand markets, research companies, track your "
        "watchlist, and learn about finance — all through natural conversation.\n\n"
        "Before we dive in, I'd love to personalize your experience. "
        "I'll ask a few quick questions (you can skip any of them).\n\n"
        "Let's start simple — **what should I call you?** 😊"
    )
