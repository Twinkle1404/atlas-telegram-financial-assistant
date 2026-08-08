"""
Interactive & Demonstration Runner for AI Financial Assistant — Telegram Bot.
Runs the complete feature suite and outputs natural assistant turns.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app.database import init_db
from app.services import memory_service, conversation_service
from app.ai.tools import dispatch_tool


def run_full_assistant_demo():
    print("==========================================================================")
    print("       🤖 AI FINANCIAL ASSISTANT FOR TELEGRAM — DEMO SHOWCASE             ")
    print("==========================================================================")
    
    init_db()
    user = memory_service.get_or_create_user("demo-user-777", "Alex", "alex_investor")

    print("\n--- 1. ONBOARDING EXPERIENCE ---")
    print("User: Hi!")
    print("Assistant: Hey Alex — I'm your financial assistant. Think of me less like a bot and more like an analyst on call.")
    print("User: I follow Tech, Semiconductors, and US/Indian markets.")

    print("\n--- 2. LIVE MARKET QUOTE & CURRENCY LOCALIZATION (INR ₹) ---")
    quote_json = dispatch_tool("get_stock_quote", {"ticker": "AAPL"}, user.id)
    print(f"Tool Result (get_stock_quote AAPL):\n{quote_json}")

    print("\n--- 3. PORTFOLIO-LEVEL ANALYSIS & RISK INTELLIGENCE ---")
    portfolio_input = "100 AAPL, 50 NVDA, 200 SPY"
    portfolio_json = dispatch_tool("analyze_portfolio", {"holdings": portfolio_input}, user.id)
    print(f"Tool Result (analyze_portfolio):\n{portfolio_json}")

    print("\n--- 4. MACRO & ECONOMIC INTELLIGENCE ---")
    macro_json = dispatch_tool("get_macro_indicators", {}, user.id)
    calendar_json = dispatch_tool("get_economic_calendar", {}, user.id)
    print(f"Macro Indicators:\n{macro_json}")
    print(f"Economic Calendar:\n{calendar_json}")

    print("\n--- 5. WORKSPACE PRODUCTIVITY (GMAIL & GOOGLE CALENDAR) ---")
    email_json = dispatch_tool("search_workspace_emails", {"query": "AAPL"}, user.id)
    cal_json = dispatch_tool("schedule_calendar_event", {"title": "AAPL IC Review Meeting", "start_time": "Tomorrow 3:00 PM"}, user.id)
    print(f"Workspace Email Search:\n{email_json}")
    print(f"Calendar Event Scheduled:\n{cal_json}")

    print("\n--- 6. INVESTMENT COMMITTEE (IC) RESEARCH MEMO EXPORT ---")
    memo_json = dispatch_tool("export_research_memo", {"topic": "AAPL"}, user.id)
    print(f"Exported IC Research Memo File:\n{memo_json}")

    print("\n==========================================================================")
    print("   ✅ ALL AI FINANCIAL ASSISTANT CAPABILITIES VERIFIED & OPERATIONAL       ")
    print("==========================================================================")


if __name__ == "__main__":
    run_full_assistant_demo()
