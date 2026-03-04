"""Observability contract tests for scheduled actions (H1)."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.models.enums import OutputMode
from src.core.observability import LLMUsage
from src.core.scheduled_actions.formatter import format_action_message
from src.core.tasks.scheduled_action_tasks import _log_run_event


def _action() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        family_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        schedule_kind="daily",
        output_mode="decision_ready",
        language="en",
        timezone="UTC",
        sources=["tasks"],
        title="Morning brief",
        instruction="Daily summary",
        next_run_at=datetime(2026, 3, 6, 8, 0, tzinfo=UTC),
        action_kind="digest",
    )


def _run() -> SimpleNamespace:
    return SimpleNamespace(
        status="success",
        model_used="gpt-5.2",
        tokens_used=123,
        duration_ms=456,
        error_code=None,
        sources_status={"tasks": {"status": "success"}},
    )


async def test_decision_ready_synthesis_sets_trace_dimensions():
    action = _action()
    action.output_mode = OutputMode.decision_ready
    payload = {"tasks": "Open tasks:\n- Pay bill"}

    with (
        patch(
            "src.core.scheduled_actions.formatter.generate_text",
            new_callable=AsyncMock,
            return_value="🎯 <b>Top priorities</b>\n• Pay bill",
        ) as mock_generate_text,
        patch(
            "src.core.scheduled_actions.formatter.get_last_usage",
            return_value=LLMUsage(tokens_input=100, tokens_output=50),
        ),
    ):
        _, model_used, tokens_used, _ = await format_action_message(
            action,
            payload,
            allow_synthesis=True,
        )

    assert model_used == "claude-sonnet-4-6"
    assert tokens_used == 150
    kwargs = mock_generate_text.await_args.kwargs
    assert kwargs["trace_name"] == "scheduled_action_synthesis"
    assert kwargs["trace_user_id"] == str(action.user_id)
    assert kwargs["trace_intent"] == "scheduled_action"


def test_log_run_event_includes_observability_dimensions():
    action = _action()
    run = _run()

    with patch("src.core.tasks.scheduled_action_tasks.logger.info") as mock_info:
        _log_run_event(
            "scheduled_action_run_succeeded",
            action,
            run,
            fallback_used=True,
        )

    mock_info.assert_called_once()
    fmt = mock_info.call_args.args[0]
    assert "model_used=%s" in fmt
    assert "fallback_used=%s" in fmt
    assert "tokens_used=%s" in fmt
    assert "duration_ms=%s" in fmt
    args = mock_info.call_args.args
    assert run.model_used in args
    assert run.tokens_used in args
    assert run.duration_ms in args
