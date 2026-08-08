"""
Tests for workspace productivity integration service.
"""
from app.services import workspace_service


def test_search_emails():
    results = workspace_service.search_emails("AAPL")
    assert len(results) >= 1
    assert "subject" in results[0]


def test_schedule_calendar_event():
    evt = workspace_service.schedule_calendar_event("AAPL IC Meeting", "Tomorrow 3 PM")
    assert evt["status"] == "scheduled"
    assert evt["title"] == "AAPL IC Meeting"
    assert "calendar_link" in evt


def test_analyze_spreadsheet():
    res = workspace_service.analyze_spreadsheet("non_existent_file.csv")
    assert "summary" in res
    assert "anomalies_detected" in res


def test_search_google_drive():
    docs = workspace_service.search_google_drive("Semiconductor")
    assert len(docs) >= 1
    assert "title" in docs[0]
