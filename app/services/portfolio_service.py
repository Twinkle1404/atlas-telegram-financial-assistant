"""
Portfolio-level intelligence service: parses user portfolio holdings,
computes total market value in Indian Rupees (₹), position weightings,
sector concentration, aggregate beta, and key risk flags.
"""
import re
import logging
from app.services import market_data

logger = logging.getLogger(__name__)


def parse_holdings_text(text: str) -> list[dict]:
    """
    Parses natural language holding descriptions like:
    "100 AAPL, 50 NVDA, 200 shares of SPY" or "RELIANCE: 50, TCS: 30"
    """
    holdings = []
    # Match patterns like: 100 AAPL, 50 shares of TSLA, NVDA 25, MSFT: 10
    pattern = re.compile(r'(?:(\d+(?:\.\d+)?)\s*(?:shares\s+of\s+)?([A-Za-z\.\-]+))|(?:([A-Za-z\.\-]+)\s*[:=]\s*(\d+(?:\.\d+)?))', re.IGNORECASE)
    
    for match in pattern.finditer(text):
        g1, g2, g3, g4 = match.groups()
        if g1 and g2:
            shares = float(g1)
            ticker = g2.upper().strip()
        elif g3 and g4:
            ticker = g3.upper().strip()
            shares = float(g4)
        else:
            continue
        
        # Filter out common stop words if captured as ticker
        if ticker in ("SHARES", "OF", "AND", "STOCKS", "IN", "MY", "PORTFOLIO"):
            continue
            
        holdings.append({"ticker": ticker, "shares": shares})

    return holdings


def analyze_portfolio(holdings: list[dict] | str) -> dict:
    """
    Analyzes a list of holdings `[{"ticker": "AAPL", "shares": 100}, ...]`.
    Calculates total value in Rupees (₹), weightings, sector breakdown,
    weighted aggregate beta, weighted P/E, and automated risk flags.
    """
    if isinstance(holdings, str):
        holdings = parse_holdings_text(holdings)

    if not holdings:
        return {"error": "No valid holdings detected. Example format: '100 AAPL, 50 NVDA, 200 SPY'"}

    positions = []
    total_value_inr = 0.0

    for item in holdings:
        ticker = item["ticker"].upper()
        shares = float(item["shares"])
        
        try:
            quote = market_data.get_quote(ticker)
            fundamentals = market_data.get_fundamentals(ticker)
        except Exception as exc:
            logger.warning("Failed to fetch data for portfolio ticker %s: %s", ticker, exc)
            quote = {}
            fundamentals = {}

        price_inr = quote.get("price_inr") or quote.get("price") or 0.0
        position_value_inr = shares * price_inr
        total_value_inr += position_value_inr

        positions.append({
            "ticker": ticker,
            "shares": shares,
            "price_inr": price_inr,
            "formatted_price_inr": f"₹{price_inr:,.2f}",
            "market_value_inr": position_value_inr,
            "formatted_market_value_inr": f"₹{position_value_inr:,.2f}",
            "sector": fundamentals.get("sector") or "Unclassified",
            "beta": fundamentals.get("beta"),
            "pe_ratio": fundamentals.get("pe_ratio"),
            "dividend_yield": fundamentals.get("dividend_yield"),
            "change_pct": quote.get("change_pct"),
        })

    if total_value_inr == 0:
        return {"error": "Unable to calculate portfolio market value from provided tickers."}

    # Weightings and aggregations
    sectors_breakdown = {}
    weighted_beta = 0.0
    beta_weight_total = 0.0
    weighted_pe = 0.0
    pe_weight_total = 0.0

    for pos in positions:
        weight = pos["market_value_inr"] / total_value_inr
        pos["weight_pct"] = round(weight * 100, 2)

        sec = pos["sector"]
        sectors_breakdown[sec] = round(sectors_breakdown.get(sec, 0.0) + (weight * 100), 2)

        if pos["beta"] is not None:
            weighted_beta += weight * pos["beta"]
            beta_weight_total += weight

        if pos["pe_ratio"] is not None and pos["pe_ratio"] > 0:
            weighted_pe += weight * pos["pe_ratio"]
            pe_weight_total += weight

    # Normalize weighted metrics if partial metrics exist
    portfolio_beta = round(weighted_beta / beta_weight_total, 2) if beta_weight_total > 0 else None
    portfolio_pe = round(weighted_pe / pe_weight_total, 2) if pe_weight_total > 0 else None

    # Automated Risk Flags
    risk_flags = []
    
    # 1. Single stock concentration check
    for pos in positions:
        if pos["weight_pct"] >= 25.0:
            risk_flags.append(
                f"🚨 Single-Stock Concentration: {pos['ticker']} represents {pos['weight_pct']}% of portfolio."
            )

    # 2. Sector concentration check
    for sec, sec_weight in sectors_breakdown.items():
        if sec_weight >= 40.0:
            risk_flags.append(
                f"⚠️ Sector Tilting: Heavy exposure to {sec} ({sec_weight}% of portfolio)."
            )

    # 3. High volatility / Beta check
    if portfolio_beta and portfolio_beta > 1.25:
        risk_flags.append(
            f"⚡ Volatility Risk: Aggregate portfolio beta is {portfolio_beta} (higher risk than broader market)."
        )

    # 4. High valuation check
    if portfolio_pe and portfolio_pe > 35.0:
        risk_flags.append(
            f"📊 Valuation Premium: Weighted average P/E is {portfolio_pe}x (elevated earnings multiple)."
        )

    return {
        "total_value_inr": round(total_value_inr, 2),
        "formatted_total_value_inr": f"₹{total_value_inr:,.2f}",
        "holdings_count": len(positions),
        "positions": positions,
        "sector_breakdown_pct": sectors_breakdown,
        "aggregate_portfolio_beta": portfolio_beta,
        "weighted_average_pe": portfolio_pe,
        "risk_flags": risk_flags if risk_flags else ["✅ Balanced risk profile; no critical concentration flags."],
    }
