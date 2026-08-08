import json
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from app.database import Base


class User(Base):
    """
    One row per Telegram user. `profile_json` holds the evolving, freeform
    picture the assistant builds up over time (role, followed tickers,
    sectors, preferences, learned facts) -- deliberately schemaless so the
    assistant can keep enriching it via conversation without migrations.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, default="")
    username = Column(String, default="")
    timezone = Column(String, default="UTC")

    onboarding_stage = Column(String, default="new")  # new -> in_progress -> done
    briefing_hour_local = Column(Integer, default=8)
    briefing_enabled = Column(Boolean, default=True)
    evening_summary_enabled = Column(Boolean, default=False)

    # Freeform, continuously-updated personalization memory (see memory_service.py)
    profile_json = Column(Text, default="{}")

    # OAuth tokens for connected productivity tools, stored as JSON (demo-grade; encrypt in prod)
    integrations_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)

    def profile(self) -> dict:
        try:
            return json.loads(self.profile_json or "{}")
        except json.JSONDecodeError:
            return {}

    def set_profile(self, data: dict):
        self.profile_json = json.dumps(data)

    def integrations(self) -> dict:
        try:
            return json.loads(self.integrations_json or "{}")
        except json.JSONDecodeError:
            return {}

    def set_integrations(self, data: dict):
        self.integrations_json = json.dumps(data)
