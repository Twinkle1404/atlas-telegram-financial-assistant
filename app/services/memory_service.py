"""
Manages the user's evolving profile -- the thing that makes the assistant
feel like it actually knows the user instead of resetting every message.

Profile shape (stored as JSON on User.profile_json):
{
  "role": "Analyst",
  "sectors_followed": ["AI", "semiconductors"],
  "watchlist_context": ["NVDA", "AMD"],
  "insight_preferences": ["earnings", "SEC filings"],
  "learned_facts": ["Prefers concise bullet-point summaries", ...]
}
"""
from app.database import get_session
from app.models.user import User

MAX_LEARNED_FACTS = 40


def get_or_create_user(telegram_id: str, first_name: str, username: str) -> User:
    with get_session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            return _detached_copy(user)
        user = User(telegram_id=telegram_id, first_name=first_name, username=username)
        session.add(user)
        session.flush()
        return _detached_copy(user)


def _detached_copy(user: User) -> User:
    """Return a plain copy so callers can read attrs after the session closes."""
    session_state = {c.name: getattr(user, c.name) for c in user.__table__.columns}
    detached = User(**{k: v for k, v in session_state.items() if k != "id"})
    detached.id = session_state["id"]
    return detached


def get_user_by_id(user_id: int) -> User | None:
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        return _detached_copy(user) if user else None


def update_profile(user_id: int, patch: dict):
    """Shallow-merges `patch` into the stored profile (lists are unioned)."""
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        profile = user.profile()
        for key, value in patch.items():
            if key == "learned_facts":
                continue  # handled by add_learned_fact to dedupe/cap
            if isinstance(value, list) and isinstance(profile.get(key), list):
                profile[key] = sorted(set(profile[key]) | set(value))
            elif value not in (None, "", []):
                profile[key] = value
        user.set_profile(profile)


def add_learned_fact(user_id: int, fact: str):
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        profile = user.profile()
        facts = profile.get("learned_facts", [])
        if fact not in facts:
            facts.append(fact)
        profile["learned_facts"] = facts[-MAX_LEARNED_FACTS:]
        user.set_profile(profile)


def mark_onboarded(user_id: int, briefing_hour: int | None = None):
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        user.onboarding_stage = "done"
        if briefing_hour is not None:
            user.briefing_hour_local = briefing_hour


def touch_last_active(user_id: int):
    from datetime import datetime
    with get_session() as session:
        user = session.query(User).filter_by(id=user_id).first()
        user.last_active_at = datetime.utcnow()
