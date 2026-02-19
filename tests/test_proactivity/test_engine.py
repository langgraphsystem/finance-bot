"""Tests for proactivity engine."""

from unittest.mock import AsyncMock, patch

from src.proactivity.engine import _format_trigger, run_for_user


async def test_run_for_user_no_triggers():
    with patch(
        "src.proactivity.engine.evaluate_triggers",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await run_for_user("uid", "fid")
    assert result == []


async def test_run_for_user_silent_mode_suppresses():
    fired = [
        {"name": "task_deadline", "action": "deadline_warning", "data": {"tasks": []}},
    ]
    with patch(
        "src.proactivity.engine.evaluate_triggers",
        new_callable=AsyncMock,
        return_value=fired,
    ):
        result = await run_for_user(
            "uid", "fid", communication_mode="silent"
        )
    # task_deadline is suppressed in silent mode
    assert result == []


async def test_run_for_user_suppressed_triggers():
    fired = [
        {"name": "budget_alert", "action": "budget_warning", "data": {
            "total_budget": 1000, "total_spent": 900, "ratio_pct": 90,
        }},
    ]
    with patch(
        "src.proactivity.engine.evaluate_triggers",
        new_callable=AsyncMock,
        return_value=fired,
    ):
        result = await run_for_user(
            "uid", "fid", suppressed_triggers=["budget_alert"]
        )
    assert result == []


async def test_run_for_user_formats_budget_alert():
    fired = [
        {"name": "budget_alert", "action": "budget_warning", "data": {
            "total_budget": 1000, "total_spent": 900, "ratio_pct": 90,
        }},
    ]
    with patch(
        "src.proactivity.engine.evaluate_triggers",
        new_callable=AsyncMock,
        return_value=fired,
    ):
        result = await run_for_user("uid", "fid")

    assert len(result) == 1
    assert result[0]["action"] == "budget_warning"
    assert "90%" in result[0]["message"]
    assert "$900" in result[0]["message"]


async def test_format_trigger_task_deadline():
    data = {
        "name": "task_deadline",
        "action": "deadline_warning",
        "data": {"tasks": [{"title": "Buy milk", "due_at": "2026-02-19T14:00:00"}]},
    }
    msg = await _format_trigger(data, "en")
    assert "Buy milk" in msg
    assert "Upcoming deadlines" in msg


async def test_format_trigger_overdue_invoice():
    data = {
        "name": "overdue_invoice",
        "action": "invoice_reminder",
        "data": {"overdue": [{"name": "Rent", "amount": 1500, "due": "2026-02-10"}]},
    }
    msg = await _format_trigger(data, "en")
    assert "1 overdue" in msg
    assert "$1500" in msg
