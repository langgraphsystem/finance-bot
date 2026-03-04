"""Tests for scheduled action formatter."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.core.models.enums import OutputMode
from src.core.observability import LLMUsage
from src.core.scheduled_actions.formatter import format_action_message, format_compact_message


def _action(output_mode: OutputMode = OutputMode.compact, sources: list[str] | None = None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Morning brief",
        instruction="Send me summary",
        sources=sources or ["tasks", "calendar"],
        timezone="UTC",
        next_run_at=datetime(2026, 3, 4, 8, 0, tzinfo=UTC),
        language="en",
        output_mode=output_mode,
    )


async def test_format_action_message_compact_mode():
    action = _action(OutputMode.compact)
    payload = {"tasks": "Open tasks:\n- Pay bill", "calendar": "Today's calendar:\n- 10:00 Call"}

    text, model_used, tokens_used, fallback_used = await format_action_message(
        action,
        payload,
        allow_synthesis=False,
    )

    assert "<b>Good morning!" in text
    assert "Pay bill" in text
    assert model_used is None
    assert tokens_used is None
    assert fallback_used is False


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
        text, model_used, tokens_used, fallback_used = await format_action_message(
            action,
            payload,
            allow_synthesis=True,
        )

    assert "Top priorities" in text
    assert model_used == "gpt-5.2"
    assert tokens_used == 140
    assert fallback_used is True


async def test_format_action_message_decision_ready_full_fallback_to_template():
    action = _action(OutputMode.decision_ready)
    payload = {"tasks": "Open tasks:\n- Pay bill"}

    with patch(
        "src.core.scheduled_actions.formatter.generate_text",
        new_callable=AsyncMock,
        side_effect=RuntimeError("all providers failed"),
    ):
        text, model_used, tokens_used, fallback_used = await format_action_message(
            action,
            payload,
            allow_synthesis=True,
        )

    assert "Pay bill" in text
    assert model_used == "template_fallback"
    assert tokens_used is None
    assert fallback_used is True


def test_trust_footer_shows_source_count_and_time():
    """G4: compact message includes trust footer with source count and freshness."""
    action = _action(OutputMode.compact)
    payload = {"tasks": "Open tasks:\n- Pay bill", "calendar": "Today:\n- 10:00 Call"}
    sources_status = {
        "tasks": {"status": "ok"},
        "calendar": {"status": "ok"},
    }

    text = format_compact_message(action, payload, sources_status=sources_status)

    assert "📡 2/2" in text
    assert "08:00" in text


def test_trust_footer_with_failed_sources():
    """G4: trust footer reflects failed source count correctly."""
    action = _action(OutputMode.compact)
    payload = {"tasks": "Open tasks:\n- Pay bill", "calendar": ""}
    sources_status = {
        "tasks": {"status": "ok"},
        "calendar": {"status": "failed", "error": "timeout"},
    }

    text = format_compact_message(action, payload, sources_status=sources_status)

    assert "📡 1/2" in text
    assert "⚠️" in text


def test_finance_overlay_adds_budget_bar_risk_and_trend():
    action = _action(OutputMode.compact, sources=["money_summary"])
    payload = {
        "money_summary": (
            "Money:\n"
            "- Yesterday: $120.00 spent\n"
            "- This month: $1200.00 total\n"
            "- Monthly budget: $1000.00\n"
            "- Budget usage: 120.00%"
        ),
    }

    text = format_compact_message(action, payload)

    assert "🔴 Budget usage" in text
    assert "<code>██████████</code> 120%" in text
    assert "Spending trend" in text
    assert "📈" in text or "📉" in text
