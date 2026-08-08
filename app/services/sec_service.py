"""
SEC EDGAR integration -- free, no API key, just requires a descriptive
User-Agent per SEC's fair access policy. Two-step lookup: ticker -> CIK,
then CIK -> recent filings.
"""
import requests
from app.config import settings

_HEADERS = {"User-Agent": settings.SEC_USER_AGENT}
_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_ticker_to_cik_cache: dict | None = None


def _load_ticker_map() -> dict:
    global _ticker_to_cik_cache
    if _ticker_to_cik_cache is None:
        resp = requests.get(_TICKER_MAP_URL, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _ticker_to_cik_cache = {
            row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in data.values()
        }
    return _ticker_to_cik_cache


def get_recent_filings(ticker: str, form_type: str | None = None, max_items: int = 5) -> list[dict]:
    try:
        cik = _load_ticker_map().get(ticker.upper())
        if not cik:
            return [{"error": f"No SEC record found for ticker {ticker}"}]

        resp = requests.get(_SUBMISSIONS_URL.format(cik=cik), headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        recent = resp.json().get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])

        results = []
        for i in range(len(forms)):
            if form_type and forms[i].upper() != form_type.upper():
                continue
            accession_nodash = accessions[i].replace("-", "")
            results.append(
                {
                    "form": forms[i],
                    "filed_date": dates[i],
                    "url": (
                        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{accession_nodash}/{docs[i]}"
                    ),
                }
            )
            if len(results) >= max_items:
                break
        return results
    except Exception as exc:
        return [{"error": str(exc)}]
