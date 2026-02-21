"""Tests for proactivity engine."""

from unittest.mock import AsyncMock, patch

import pytest

from src.proactivity.engine import _format_trigger, run_for_user


@pytest.fixture(autouse=True)
def _mock_redis():
    """Mock Redis for all engine tests — cooldown keys don't exist by default."""
    mock = AsyncMock()
    mock.exists = AsyncMock(return_value=0)
    mock.set = AsyncMock()
    with patch("src.proactivity.engine.redis", mock):
        yield mock


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
        result = await run_for_user("uid", "fid", communication_mode="silent")
    # task_deadline is suppressed in silent mode
    assert result == []


async def test_run_for_user_suppressed_triggers():
    fired = [
        {
            "name": "budget_alert",
            "action": "budget_warning",
            "data": {
                "total_budget": 1000,
                "total_spent": 900,
                "ratio_pct": 90,
            },
        },
    ]
    with patch(
        "src.proactivity.engine.evaluate_triggers",
        new_callable=AsyncMock,
        return_value=fired,
    ):
        result = await run_for_user("uid", "fid", suppressed_triggers=["budget_alert"])
    assert result == []


async def test_run_for_user_formats_budget_alert(_mock_redis):
    fired = [
        {
            "name": "budget_alert",
            "action": "budget_warning",
            "data": {
                "total_budget": 1000,
                "total_spent": 900,
                "ratio_pct": 90,
            },
        },
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
    # Verify cooldown was set in Redis
    _mock_redis.set.assert_called_once()
    call_args = _mock_redis.set.call_args
    assert "proactive:uid:budget_alert" in call_args[0]


async def test_run_for_user_skips_cooldown(_mock_redis):
    """When a trigger was sent recently, it should be skipped."""
    _mock_redis.exists = AsyncMock(return_value=1)  # cooldown key exists
    fired = [
        {
            "name": "budget_alert",
            "action": "budget_warning",
            "data": {"total_budget": 1000, "total_spent": 900, "ratio_pct": 90},
        },
    ]
    with patch(
        "src.proactivity.engine.evaluate_triggers",
        new_callable=AsyncMock,
        return_value=fired,
    ):
        result = await run_for_user("uid", "fid")
    assert result == []


# --- English locale ---


async def test_format_trigger_task_deadline_en():
    data = {
        "name": "task_deadline",
        "action": "deadline_warning",
        "data": {"tasks": [{"title": "Buy milk", "due_at": "2026-02-19T14:00:00"}]},
    }
    msg = await _format_trigger(data, "en")
    assert "Buy milk" in msg
    assert "Upcoming deadlines" in msg


async def test_format_trigger_overdue_invoice_en():
    data = {
        "name": "overdue_invoice",
        "action": "invoice_reminder",
        "data": {"overdue": [{"name": "Rent", "amount": 1500, "due": "2026-02-10"}]},
    }
    msg = await _format_trigger(data, "en")
    assert "1 overdue" in msg
    assert "$1500" in msg


async def test_format_trigger_budget_alert_en():
    data = {
        "name": "budget_alert",
        "action": "budget_warning",
        "data": {"total_budget": 2000, "total_spent": 1800, "ratio_pct": 90},
    }
    msg = await _format_trigger(data, "en")
    assert "Budget alert" in msg
    assert "$1800" in msg


# --- Russian locale ---


async def test_format_trigger_task_deadline_ru():
    data = {
        "name": "task_deadline",
        "action": "deadline_warning",
        "data": {"tasks": [{"title": "Купить молоко", "due_at": "2026-02-19T14:00:00"}]},
    }
    msg = await _format_trigger(data, "ru")
    assert "Купить молоко" in msg
    assert "Ближайшие дедлайны" in msg
    assert "Перенести" in msg


async def test_format_trigger_budget_alert_ru():
    data = {
        "name": "budget_alert",
        "action": "budget_warning",
        "data": {"total_budget": 2000, "total_spent": 1800, "ratio_pct": 90},
    }
    msg = await _format_trigger(data, "ru")
    assert "Бюджет" in msg
    assert "$1800" in msg
    assert "категориям" in msg


async def test_format_trigger_overdue_invoice_ru():
    data = {
        "name": "overdue_invoice",
        "action": "invoice_reminder",
        "data": {"overdue": [{"name": "Rent", "amount": 1500, "due": "2026-02-10"}]},
    }
    msg = await _format_trigger(data, "ru")
    assert "Просроченных платежей" in msg
    assert "$1500" in msg
    assert "Показать список" in msg
