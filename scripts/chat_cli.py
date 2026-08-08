"""
Dev utility: talk to the assistant straight from the terminal, using the
exact same pipeline (memory, tools, onboarding) the Telegram bot uses --
just swap the transport. Handy for iterating in VS Code without needing a
live Telegram connection for every test.

Usage:
    python scripts/chat_cli.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import init_db
from app.services import memory_service, conversation_service
from app.ai import claude_client
from app.bot import onboarding

DEV_TELEGRAM_ID = "cli-dev-user"


def main():
    init_db()
    user = memory_service.get_or_create_user(DEV_TELEGRAM_ID, "Dev", "dev")
    print("=== Financial Assistant CLI (Ctrl+C to quit) ===")
    if user.onboarding_stage != "done":
        print(f"\nAssistant: {onboarding.welcome_message(user.first_name)}\n")

    while True:
        try:
            text = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not text:
            continue

        conversation_service.log_message(user.id, "user", text)
        user = memory_service.get_user_by_id(user.id)

        if user.onboarding_stage != "done":
            history = conversation_service.get_recent_history(user.id, limit=13)[:-1]
            reply = claude_client.generate_onboarding_reply(history, text)
            conversation_service.log_message(user.id, "assistant", reply)
            turns = len([m for m in history if m["role"] == "user"]) + 1
            if turns >= onboarding.MAX_ONBOARDING_TURNS or any(
                s in text.lower() for s in onboarding._DONE_SIGNALS
            ):
                transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history) + f"\nuser: {text}"
                profile = claude_client.extract_onboarding_profile(transcript)
                if profile:
                    memory_service.update_profile(user.id, profile)
                memory_service.mark_onboarded(user.id, profile.get("briefing_hour_local"))
        else:
            history = conversation_service.get_recent_history(user.id)[:-1]
            reply = claude_client.generate_reply(user.id, user.profile(), history, text)
            conversation_service.log_message(user.id, "assistant", reply)

        print(f"\nAssistant: {reply}\n")


if __name__ == "__main__":
    main()
