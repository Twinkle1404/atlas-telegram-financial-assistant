from app.services import memory_service
from app.ai.tools import dispatch_tool
import json


def test_add_to_watchlist_then_duplicate_is_idempotent():
    user = memory_service.get_or_create_user("222", "Priya", "priya_pm")

    first = json.loads(dispatch_tool(
        "add_to_watchlist", {"ticker": "nvda", "reason": "core holding"}, user.id
    ))
    assert first["status"] == "added"
    assert first["ticker"] == "NVDA"

    second = json.loads(dispatch_tool(
        "add_to_watchlist", {"ticker": "nvda", "reason": "core holding"}, user.id
    ))
    assert second["status"] == "already_watching"


def test_remove_from_watchlist_not_found():
    user = memory_service.get_or_create_user("333", "Owen", "owen_vc")
    result = json.loads(dispatch_tool("remove_from_watchlist", {"ticker": "TSLA"}, user.id))
    assert result["status"] == "not_found"


def test_remove_from_watchlist_after_add():
    user = memory_service.get_or_create_user("444", "Mei", "mei_analyst")
    dispatch_tool("add_to_watchlist", {"ticker": "AAPL"}, user.id)
    result = json.loads(dispatch_tool("remove_from_watchlist", {"ticker": "aapl"}, user.id))
    assert result["status"] == "removed"


def test_create_reminder_schedules_future_event():
    user = memory_service.get_or_create_user("555", "Jon", "jon_founder")
    result = json.loads(
        dispatch_tool("create_reminder", {"description": "Earnings call", "minutes_from_now": 30}, user.id)
    )
    assert result["status"] == "scheduled"
    assert "fire_at_utc" in result


def test_update_user_memory_persists_fact():
    user = memory_service.get_or_create_user("666", "Alex", "alex_trader")
    dispatch_tool("update_user_memory", {"fact": "Focuses on EV supply chain"}, user.id)

    updated = memory_service.get_user_by_id(user.id)
    assert "Focuses on EV supply chain" in updated.profile()["learned_facts"]


def test_unknown_tool_returns_error_without_raising():
    user = memory_service.get_or_create_user("777", "Kim", "kim")
    result = json.loads(dispatch_tool("not_a_real_tool", {}, user.id))
    assert "error" in result
