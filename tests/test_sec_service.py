from unittest.mock import patch, MagicMock
from app.services import sec_service


def _mock_response(json_data):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = json_data
    return mock


def test_get_recent_filings_maps_ticker_to_cik_and_filters_form_type():
    sec_service._ticker_to_cik_cache = None  # reset module cache between tests

    ticker_map_response = _mock_response({"0": {"ticker": "AAPL", "cik_str": 320193}})
    submissions_response = _mock_response(
        {
            "filings": {
                "recent": {
                    "form": ["10-K", "8-K", "4"],
                    "filingDate": ["2026-01-15", "2026-02-01", "2026-02-10"],
                    "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"],
                    "primaryDocument": ["10k.htm", "8k.htm", "form4.htm"],
                }
            }
        }
    )

    with patch("app.services.sec_service.requests.get", side_effect=[ticker_map_response, submissions_response]):
        results = sec_service.get_recent_filings("AAPL", form_type="8-K")

    assert len(results) == 1
    assert results[0]["form"] == "8-K"
    assert "sec.gov/Archives" in results[0]["url"]


def test_get_recent_filings_unknown_ticker_returns_error():
    sec_service._ticker_to_cik_cache = {}  # simulate loaded map with no match

    with patch("app.services.sec_service.requests.get") as mock_get:
        results = sec_service.get_recent_filings("NOTAREALTICKER")

    assert "error" in results[0]
    mock_get.assert_not_called()
