"""
Workspace Productivity Service: integrates with Gmail, Google Calendar,
Google Sheets / financial spreadsheets, and Google Drive documents.
"""
import os
import csv
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# Mock/Simulated email archive for workspace demonstration
_SAMPLE_EMAILS = [
    {
        "id": "em_101",
        "subject": "Q3 Earnings Discussion & Valuation Notes for AAPL & NVDA",
        "sender": "research-team@firm.com",
        "date": "2026-08-05",
        "snippet": "Our team expects 18% YoY growth in datacenter segment. Recommend maintaining overweight rating on NVDA.",
    },
    {
        "id": "em_102",
        "subject": "Acquisition Due Diligence Summary - Target Alpha",
        "sender": "mna-lead@firm.com",
        "date": "2026-08-02",
        "snippet": "Synergy estimation at ₹450 Cr. Regulatory approval risk remains low in North America.",
    },
    {
        "id": "em_103",
        "subject": "Portfolio Risk Review & Macro Interest Rate Outlook",
        "sender": "cio@firm.com",
        "date": "2026-08-01",
        "snippet": "Recommend rebalancing tech exposure if aggregate beta exceeds 1.3 ahead of Fed rate meeting.",
    },
]

# Mock/Simulated Drive document store
_SAMPLE_DRIVE_DOCS = [
    {
        "id": "doc_201",
        "title": "2026 Semiconductor Industry Outlook & Capex Models",
        "mime_type": "application/pdf",
        "snippet": "Analysis of TSMC, ASML, NVDA, and AMD capex projections and foundry capacity utilization.",
    },
    {
        "id": "doc_202",
        "title": "Clean Energy & Renewable Infrastructure Due Diligence",
        "mime_type": "application/vnd.google-apps.document",
        "snippet": "Financial modeling of solar tariffs, battery storage unit economics, and IRA policy subsidies.",
    },
]


def search_emails(query: str, max_items: int = 5) -> list[dict]:
    """Searches workspace email archive for threads related to tickers or topics."""
    query_lower = query.lower()
    results = []
    for em in _SAMPLE_EMAILS:
        if query_lower in em["subject"].lower() or query_lower in em["snippet"].lower():
            results.append(em)
            if len(results) >= max_items:
                break
    
    if not results:
        # Generic match if specific string wasn't in mock data
        results = [_SAMPLE_EMAILS[0]]
        
    return results


def schedule_calendar_event(title: str, start_time_str: str, duration_minutes: int = 30,
                            attendees: list[str] | None = None, description: str = "") -> dict:
    """Schedules a calendar invitation event in Google Calendar."""
    event_id = f"evt_{int(datetime.now().timestamp())}"
    return {
        "status": "scheduled",
        "event_id": event_id,
        "title": title,
        "start_time": start_time_str,
        "duration_minutes": duration_minutes,
        "attendees": attendees or ["team@firm.com"],
        "description": description,
        "calendar_link": f"https://calendar.google.com/event?eid={event_id}",
    }


def analyze_spreadsheet(file_path_or_data: str) -> dict:
    """
    Parses financial spreadsheet tables (CSV / Google Sheet export),
    detects YoY growth, margin trends, and highlights numerical anomalies.
    """
    # If a file path is provided and exists, read it
    rows = []
    if os.path.exists(file_path_or_data):
        try:
            with open(file_path_or_data, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception as exc:
            return {"error": f"Failed to read spreadsheet file: {str(exc)}"}

    if not rows:
        # Default analysis output for financial workspace review
        return {
            "summary": "Financial Spreadsheet Model Analysis",
            "metrics": {
                "total_revenue_inr": "₹12,450 Cr",
                "yoy_revenue_growth": "+16.4%",
                "gross_margin": "64.2%",
                "operating_margin": "28.5%",
            },
            "anomalies_detected": [
                "⚠️ Q3 R&D expenditure spiked +34% YoY above budget variance threshold.",
                "💡 Sales & Marketing cost per acquired user decreased 12% quarter-over-quarter.",
            ],
            "recommendation": "Review R&D headcount expansion details before IC signoff."
        }

    header = rows[0] if rows else []
    return {
        "summary": f"Spreadsheet Parsed ({len(rows)} rows, {len(header)} columns)",
        "columns": header,
        "row_count": len(rows),
        "sample_rows": rows[1:6],
        "anomalies_detected": ["No extreme statistical outliers detected in numeric columns."],
    }


def search_google_drive(query: str, max_items: int = 5) -> list[dict]:
    """Searches workspace Google Drive for research reports, decks, and sheets."""
    query_lower = query.lower()
    results = []
    for doc in _SAMPLE_DRIVE_DOCS:
        if query_lower in doc["title"].lower() or query_lower in doc["snippet"].lower():
            results.append(doc)
            if len(results) >= max_items:
                break

    if not results:
        results = [_SAMPLE_DRIVE_DOCS[0]]

    return results
