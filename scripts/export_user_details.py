"""
Export Full User Details & Activity Audit Log.
Run: python scripts/export_user_details.py
"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import get_session
from app.models.user import User
from app.models.conversation import Message
from app.models.watchlist import WatchlistItem

def main():
    with get_session() as session:
        users = session.query(User).order_by(User.id).all()
        print(f"📊 **TOTAL REGISTERED BOT USERS:** `{len(users)}`")
        print("=" * 80)
        
        for u in users:
            msgs_count = session.query(Message).filter_by(user_id=u.id).count()
            watchlist = session.query(WatchlistItem).filter_by(user_id=u.id).all()
            tickers = [w.ticker for w in watchlist]
            username = f"@{u.username}" if u.username else "No username"
            last_active = u.last_active_at.strftime("%Y-%m-%d %H:%M:%S") if u.last_active_at else "Never"
            created_at = u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "Unknown"
            
            print(f"👤 **User ID:** `{u.id}`")
            print(f"• **Telegram ID:** `{u.telegram_id}`")
            print(f"• **Name:** {u.first_name or 'Unknown'}")
            print(f"• **Username:** {username}")
            print(f"• **Onboarding Stage:** {u.onboarding_stage}")
            print(f"• **Created At:** `{created_at}`")
            print(f"• **Last Active:** `{last_active}`")
            print(f"• **Total Messages:** {msgs_count}")
            print(f"• **Watchlist Tickers:** {', '.join(tickers) if tickers else 'None'}")
            print(f"• **Profile:** {u.profile_json}")
            print("-" * 80)

if __name__ == "__main__":
    main()
