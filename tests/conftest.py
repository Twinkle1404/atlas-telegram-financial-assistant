"""
Shared fixtures. Each test gets a clean in-memory SQLite database so tests
never depend on order or leak state -- important since the models normally
default to a file-based DB via DATABASE_URL.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-not-used")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as db_module


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    """Rebind the module-level engine/session to a fresh in-memory DB per test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_local)

    db_module.init_db()
    yield
