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
