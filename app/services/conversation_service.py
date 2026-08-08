"""Stores and retrieves chat history used both as model context and as an
audit trail / source for personalization mining."""
from app.database import get_session
from app.models.conversation import Message
from app.config import settings


def log_message(user_id: int, role: str, content: str, input_type: str = "text"):
    with get_session() as session:
        session.add(Message(user_id=user_id, role=role, content=content, input_type=input_type))


def get_recent_history(user_id: int, limit: int = None) -> list[dict]:
    limit = limit or settings.MAX_CONTEXT_MESSAGES
    with get_session() as session:
        rows = (
            session.query(Message)
            .filter_by(user_id=user_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return [{"role": r.role, "content": r.content} for r in rows]
