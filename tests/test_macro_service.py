"""
Tests for macro & economic intelligence service.
"""
from app.services import macro_service


def test_get_economic_calendar():
    events = macro_service.get_economic_calendar()
    assert len(events) >= 1
    assert "event" in events[0]
    assert "impact" in events[0]


def test_get_macro_indicators(mocker):
    mocker.patch(
        "app.services.market_data.get_quote",
        return_value={"ticker": "^TNX", "price_usd": 3.85, "change_pct": -0.5}
    )
    indicators = macro_service.get_macro_indicators()
    assert "10Y_Treasury_Yield" in indicators
    assert indicators["10Y_Treasury_Yield"]["value"] == 3.85
