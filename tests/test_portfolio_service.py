"""
Tests for portfolio analysis service.
"""
from app.services import portfolio_service


def test_parse_holdings_text():
    raw_text = "I hold 100 AAPL, 50 NVDA, and 200 shares of SPY"
    holdings = portfolio_service.parse_holdings_text(raw_text)
    tickers = [h["ticker"] for h in holdings]
    assert "AAPL" in tickers
    assert "NVDA" in tickers
    assert "SPY" in tickers


def test_analyze_portfolio_empty_returns_error():
    result = portfolio_service.analyze_portfolio("")
    assert "error" in result


def test_analyze_portfolio_valid_structure(mocker):
    mocker.patch(
        "app.services.market_data.get_quote",
        return_value={"ticker": "AAPL", "price_inr": 15000.0, "price": 15000.0, "change_pct": 1.2}
    )
    mocker.patch(
        "app.services.market_data.get_fundamentals",
        return_value={
            "sector": "Technology",
            "beta": 1.1,
            "pe_ratio": 28.5,
            "dividend_yield": 0.005
        }
    )

    holdings = [{"ticker": "AAPL", "shares": 10}]
    result = portfolio_service.analyze_portfolio(holdings)

    assert result["total_value_inr"] == 150000.0
    assert "₹150,000.00" in result["formatted_total_value_inr"]
    assert result["holdings_count"] == 1
    assert result["aggregate_portfolio_beta"] == 1.1
    assert "Technology" in result["sector_breakdown_pct"]
