"""
Admin Utility: View all registered users, activity timestamps, and message counts in Atlas Financial Assistant.
Run: python scripts/view_bot_users.py
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import get_session
from app.models.user import User
from app.models.conversation import Message
from app.models.watchlist import WatchlistItem
from app.models.document import Document

def main():
    print("=" * 60)
    print("🔍 ATLAS BOT — USER ACTIVITY & AUDIT REPORT")
    print("=" * 60)

    with get_session() as session:
        users = session.query(User).order_by(User.last_active_at.desc()).all()
        if not users:
            print("No users found in the database.")
            return

        print(f"Total Registered Users: {len(users)}\n")
        print(f"{'User ID':<8} | {'Telegram ID':<12} | {'Username':<15} | {'Name':<15} | {'Last Active':<20} | {'Msgs':<5}")
        print("-" * 85)

        for u in users:
            msg_count = session.query(Message).filter_by(user_id=u.id).count()
            last_active = u.last_active_at.strftime("%Y-%m-%d %H:%M:%S") if u.last_active_at else "Never"
            username = f"@{u.username}" if u.username else "No username"
            name = u.first_name or "Unknown"

            print(f"{u.id:<8} | {u.telegram_id:<12} | {username:<15} | {name:<15} | {last_active:<20} | {msg_count:<5}")

        print("=" * 60)

if __name__ == "__main__":
    main()
