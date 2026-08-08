from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from app.database import Base


class Message(Base):
    """
    Full conversation log. This is both the chat history shown to the model
    for context (last N rows) and the raw material the memory service mines
    for personalization signals.
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    role = Column(String, nullable=False)       # "user" | "assistant"
    content = Column(Text, nullable=False)
    input_type = Column(String, default="text")  # text | voice | image | document
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
