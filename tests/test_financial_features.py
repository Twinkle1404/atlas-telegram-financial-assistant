import pytest
from app.services import market_data


def test_get_historical_financials():
    res = market_data.get_historical_financials("TATAMOTORS.NS")
    assert res["ticker"] == "TATAMOTORS.NS"
    assert len(res["history"]) == 5
    assert len(res["turning_points"]) >= 3


def test_calculate_health_score():
    score = market_data.calculate_health_score("AMZN")
    assert score["ticker"] == "AMZN"
    assert 0.0 <= score["overall_score"] <= 10.0
    assert "Profitability" in score["factors"]


def test_get_competitors():
    comps = market_data.get_competitors("TATAMOTORS.NS")
    assert len(comps) >= 2
    tickers = [c["ticker"] for c in comps]
    assert "MARUTI.NS" in tickers or "M&M.NS" in tickers


def test_conversational_context_fallback():
    from app.ai.llm_client import _smart_fallback_response
    from app.services import conversation_service

    user_id = 99999
    # Simulate first turn discussing Tata Motors
    conversation_service.log_message(user_id, "user", "Tell me about Tata Motors")
    conversation_service.log_message(user_id, "assistant", "Tata Motors is a leading auto company.")

    # Second turn using pronoun "Is it risky?"
    res_risk = _smart_fallback_response("Is it risky?", user_id)
    assert "Risk Analysis" in res_risk or "Tata" in res_risk or "TATAMOTORS" in res_risk

def test_build_personalized_dashboard():
    from app.bot.handlers import build_personalized_dashboard
    from app.services import memory_service

    user = memory_service.get_or_create_user("test_dash_123", "Twinkle", "twinkle")
    dashboard = build_personalized_dashboard(user)

    assert "Good Morning" in dashboard or "Twinkle" in dashboard
    assert "Today's Market" in dashboard
    assert "Your Watchlist" in dashboard
    assert "Important News" in dashboard
    assert "Market Movers" in dashboard
    assert "What Matters Today" in dashboard
    assert "Learn Today" in dashboard


def test_experience_level_adaptive_responses():
    from app.ai.llm_client import _smart_fallback_response
    from app.services import memory_service, conversation_service

    user = memory_service.get_or_create_user("88888", "Test", "test")
    user_id = user.id
    conversation_service.log_message(user_id, "user", "Tell me about Tata Motors")
    conversation_service.log_message(user_id, "assistant", "Tata Motors details.")

    # Test Advanced user mode (gets all 11 metrics)
    memory_service.update_profile(user_id, {"experience_level": "advanced"})
    res_adv = _smart_fallback_response("Tell me more about TATAMOTORS.NS", user_id)
    assert "EBITDA" in res_adv
    assert "ROE" in res_adv
    assert "ROCE" in res_adv
    assert "Debt-to-Equity" in res_adv
    assert "Free Cash Flow" in res_adv
    assert "P/B Ratio" in res_adv

    # Test Beginner user mode (gets plain language explanations)
    memory_service.update_profile(user_id, {"experience_level": "beginner"})
    res_beg = _smart_fallback_response("go deeper", user_id)
    assert "P/E tells us roughly how much investors pay" in res_beg



