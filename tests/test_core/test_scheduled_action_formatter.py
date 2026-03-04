"""Tests for scheduled action formatter."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.models.enums import OutputMode
from src.core.observability import LLMUsage
from src.core.scheduled_actions.formatter import format_action_message


def _action(output_mode: OutputMode = OutputMode.compact):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Morning brief",
        instruction="Send me summary",
        sources=["tasks", "calendar"],
        timezone="UTC",
        next_run_at=datetime(2026, 3, 4, 8, 0, tzinfo=UTC),
        language="en",
        output_mode=output_mode,
    )


async def test_format_action_message_compact_mode():
    action = _action(OutputMode.compact)
    payload = {"tasks": "Open tasks:\n- Pay bill", "calendar": "Today's calendar:\n- 10:00 Call"}

    text, model_used, tokens_used = await format_action_message(
        action,
        payload,
        allow_synthesis=False,
    )

    assert "<b>Good morning!" in text
    assert "Pay bill" in text
    assert model_used is None
    assert tokens_used is None


async def test_format_action_message_decision_ready_with_fallback_chain():
    action = _action(OutputMode.decision_ready)
    payload = {"tasks": "Open tasks:\n- Pay bill", "calendar": "Today's calendar:\n- 10:00 Call"}

    async def _gen_side_effect(*args, **kwargs):  # noqa: ANN002, ANN003
        model = kwargs.get("model")
        if model == "claude-sonnet-4-6":
            raise RuntimeError("provider error")
        return "🎯 <b>Top priorities</b>\n• Pay bill\nWhat should I handle first?"

    with (
        patch(
            "src.core.scheduled_actions.formatter.generate_text",
            new_callable=AsyncMock,
            side_effect=_gen_side_effect,
        ),
        patch(
            "src.core.scheduled_actions.formatter.get_last_usage",
            return_value=LLMUsage(tokens_input=100, tokens_output=40),
        ),
    ):
        text, model_used, tokens_used = await format_action_message(
            action,
            payload,
            allow_synthesis=True,
        )

    assert "Top priorities" in text
    assert model_used == "gpt-5.2"
    assert tokens_used == 140


async def test_format_action_message_decision_ready_full_fallback_to_template():
    action = _action(OutputMode.decision_ready)
    payload = {"tasks": "Open tasks:\n- Pay bill"}

    with patch(
        "src.core.scheduled_actions.formatter.generate_text",
        new_callable=AsyncMock,
        side_effect=RuntimeError("all providers failed"),
    ):
        text, model_used, tokens_used = await format_action_message(
            action,
            payload,
            allow_synthesis=True,
        )

    assert "Pay bill" in text
    assert model_used == "template_fallback"
    assert tokens_used is None
