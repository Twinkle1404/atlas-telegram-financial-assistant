import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app.database import init_db
from app.services import memory_service, conversation_service
from app.ai.tools import dispatch_tool

def run_demo():
    init_db()
    user = memory_service.get_or_create_user("demo-user-123", "FinancePro", "financepro")
    print("--- 1. Market Quote in Indian Rupees (₹) ---")
    quote_res = dispatch_tool("get_stock_quote", {"ticker": "AAPL"}, user.id)
    print(quote_res)

    print("\n--- 2. Portfolio-Level Analysis ---")
    portfolio_res = dispatch_tool("analyze_portfolio", {"holdings": "100 AAPL, 50 NVDA, 200 SPY"}, user.id)
    print(portfolio_res)

    print("\n--- 3. Macro Indicators ---")
    macro_res = dispatch_tool("get_macro_indicators", {}, user.id)
    print(macro_res)

    print("\n--- 4. Workspace Email Search ---")
    email_res = dispatch_tool("search_workspace_emails", {"query": "AAPL"}, user.id)
    print(email_res)

    print("\n--- 5. IC Research Memo Export ---")
    memo_res = dispatch_tool("export_research_memo", {"topic": "AAPL"}, user.id)
    print(memo_res)

if __name__ == "__main__":
    run_demo()
