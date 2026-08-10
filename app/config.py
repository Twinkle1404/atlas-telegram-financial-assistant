"""
Central configuration, loaded once from environment variables.
Keeping this in one place means every other module imports `settings`
instead of reaching into os.environ directly.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "")
    SEC_USER_AGENT: str = os.getenv("SEC_USER_AGENT", "Financial Assistant contact@example.com")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./financial_assistant.db")
    DOCUMENTS_DIR: str = os.getenv("DOCUMENTS_DIR", "./data/documents")

    # Security & Whitelisting Settings
    ALLOWED_USER_IDS: list[int] = [
        int(uid.strip()) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip().isdigit()
    ]
    BOT_ADMIN_ID: str = os.getenv("BOT_ADMIN_ID", "")

    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "")

    # Product tuning knobs
    MAX_CONTEXT_MESSAGES = 20          # how many recent turns feed the model
    MAX_RESPONSE_CHARS = 1400          # keep Telegram replies scannable
    DEFAULT_BRIEFING_HOUR_LOCAL = 8    # 8am local, used until user states a preference


settings = Settings()
os.makedirs(settings.DOCUMENTS_DIR, exist_ok=True)
