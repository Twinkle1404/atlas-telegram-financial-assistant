from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Boolean
from app.database import Base


class WatchlistItem(Base):
    """A ticker/company the user wants proactively monitored."""
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    ticker = Column(String, nullable=False)
    company_name = Column(String, default="")
    reason = Column(String, default="")  # why the user cares, helps the model explain relevance
    created_at = Column(DateTime, default=datetime.utcnow)

    # Optional custom trigger, e.g. "notify if this stock moves > 5% in a day"
    move_pct_threshold = Column(Float, nullable=True)
    last_known_price = Column(Float, nullable=True)
    notify_on_filings = Column(Boolean, default=True)
    notify_on_news = Column(Boolean, default=True)


class ScheduledEvent(Base):
    """User-created reminders, e.g. 'remind me 1hr before Apple's earnings call'."""
    __tablename__ = "scheduled_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    description = Column(String, nullable=False)
    fire_at_utc = Column(DateTime, nullable=False, index=True)
    delivered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
