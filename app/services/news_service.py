"""
Company/market news. Uses NewsAPI when a key is configured (richer, more
current), otherwise falls back to yfinance's built-in news feed so the
product still works with zero paid keys.
"""
from datetime import datetime
import requests
import yfinance as yf

from app.config import settings


def get_company_news(query: str, max_items: int = 6) -> list[dict]:
    if settings.NEWSAPI_KEY:
        return _newsapi_search(query, max_items)
    return _yfinance_news(query, max_items)


def _newsapi_search(query: str, max_items: int) -> list[dict]:
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": max_items,
                "apiKey": settings.NEWSAPI_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [
            {
                "title": a["title"],
                "source": a["source"]["name"],
                "published_at": a["publishedAt"],
                "url": a["url"],
                "description": a.get("description", ""),
            }
            for a in articles
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


def _yfinance_news(query: str, max_items: int) -> list[dict]:
    try:
        t = yf.Ticker(query)
        items = t.news or []
        results = []
        for item in items[:max_items]:
            content = item.get("content", item)  # yfinance schema has shifted across versions
            results.append(
                {
                    "title": content.get("title"),
                    "source": (content.get("provider") or {}).get("displayName", "Unknown"),
                    "published_at": content.get("pubDate", ""),
                    "url": (content.get("canonicalUrl") or {}).get("url", ""),
                }
            )
        return results
    except Exception as exc:
        return [{"error": str(exc)}]
