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

    # Third turn using "What about its competitors?"
    res_comp = _smart_fallback_response("What about its competitors?", user_id)
    assert "Competitor Overview" in res_comp or "Competitor" in res_comp

