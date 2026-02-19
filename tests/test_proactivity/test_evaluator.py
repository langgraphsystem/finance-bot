"""Tests for proactivity evaluator."""

from unittest.mock import AsyncMock, patch

from src.proactivity.evaluator import MAX_DAILY_PROACTIVE, evaluate_triggers


def test_max_daily_proactive_is_five():
    assert MAX_DAILY_PROACTIVE == 5


async def test_evaluate_empty_when_no_triggers_fire():
    with patch(
        "src.proactivity.evaluator.DATA_TRIGGERS",
        [],
    ):
        result = await evaluate_triggers("uid", "fid")
    assert result == []


async def test_evaluate_collects_fired_triggers():
    mock_trigger = AsyncMock()
    mock_trigger.name = "test_trigger"
    mock_trigger.action = "test_action"
    mock_trigger.check = AsyncMock(return_value={"key": "value"})

    with patch("src.proactivity.evaluator.DATA_TRIGGERS", [mock_trigger]):
        result = await evaluate_triggers("uid", "fid")

    assert len(result) == 1
    assert result[0]["name"] == "test_trigger"
    assert result[0]["action"] == "test_action"
    assert result[0]["data"] == {"key": "value"}


async def test_evaluate_skips_non_fired_triggers():
    mock_trigger = AsyncMock()
    mock_trigger.name = "silent"
    mock_trigger.action = "noop"
    mock_trigger.check = AsyncMock(return_value={})

    with patch("src.proactivity.evaluator.DATA_TRIGGERS", [mock_trigger]):
        result = await evaluate_triggers("uid", "fid")

    assert result == []


async def test_evaluate_handles_trigger_errors():
    mock_trigger = AsyncMock()
    mock_trigger.name = "bad"
    mock_trigger.action = "fail"
    mock_trigger.check = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("src.proactivity.evaluator.DATA_TRIGGERS", [mock_trigger]):
        result = await evaluate_triggers("uid", "fid")

    assert result == []
