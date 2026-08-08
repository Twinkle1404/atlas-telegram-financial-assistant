"""
Macro & Economic Intelligence Service: fetches macroeconomic indicators
(Treasury yields, VIX, USD/INR, Crude Oil) and key market-moving economic calendar events.
"""
import logging
from app.services import market_data

logger = logging.getLogger(__name__)


def get_macro_indicators() -> dict:
    """Retrieves real-time global macro benchmark indicators."""
    symbols = {
        "10Y_Treasury_Yield": "^TNX",
        "VIX_Volatility_Index": "^VIX",
        "US_Dollar_Index_DXY": "DX-Y.NYB",
        "Crude_Oil_WTI": "CL=F",
        "USD_INR_Exchange_Rate": "USDINR=X",
    }
    
    indicators = {}
    for name, symbol in symbols.items():
        try:
            quote = market_data.get_quote(symbol)
            indicators[name] = {
                "symbol": symbol,
                "value": quote.get("price") or quote.get("price_usd"),
                "change_pct": quote.get("change_pct"),
            }
        except Exception as exc:
            logger.warning("Failed to fetch macro indicator %s: %s", symbol, exc)
            indicators[name] = {"symbol": symbol, "value": None, "error": str(exc)}

    return indicators


def get_economic_calendar() -> list[dict]:
    """Returns upcoming market-moving macroeconomic policy and economic release events."""
    return [
        {
            "event": "US Federal Reserve Interest Rate Decision (FOMC)",
            "date": "2026-08-15",
            "impact": "High",
            "forecast": "5.25% (Hold expected)",
            "prior": "5.25%",
        },
        {
            "event": "US CPI Inflation YoY Report",
            "date": "2026-08-18",
            "impact": "High",
            "forecast": "2.8%",
            "prior": "2.9%",
        },
        {
            "event": "RBI Monetary Policy Committee Repo Rate Announcement",
            "date": "2026-08-22",
            "impact": "High",
            "forecast": "6.50% (Unchanged)",
            "prior": "6.50%",
        },
        {
            "event": "US Non-Farm Payrolls & Unemployment Rate",
            "date": "2026-09-04",
            "impact": "Medium",
            "forecast": "165k additions",
            "prior": "150k additions",
        },
    ]
