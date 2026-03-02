"""Tests for weekly_digest skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.weekly_digest.handler import WeeklyDigestSkill


@pytest.fixture
def skill():
    return WeeklyDigestSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type="household",
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str = "weekly digest") -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def test_skill_attributes(skill):
    """Verify skill metadata."""
    assert skill.name == "weekly_digest"
    assert "weekly_digest" in skill.intents
    assert skill.model == "claude-sonnet-4-6"


def test_get_system_prompt(skill, ctx):
    """System prompt contains weekly/digest keywords."""
    prompt = skill.get_system_prompt(ctx)
    prompt_lower = prompt.lower()
    assert "week" in prompt_lower
    assert "digest" in prompt_lower or "review" in prompt_lower


async def test_execute_no_data(skill, ctx):
    """No data from collectors returns onboarding message."""
    msg = _msg()

    with (
        patch.object(
            skill, "_collect_spending", new_callable=AsyncMock, return_value=""
        ),
        patch.object(
            skill,
            "_collect_spending_by_category",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(
            skill,
            "_collect_completed_tasks",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(
            skill, "_collect_pending_tasks", new_callable=AsyncMock, return_value=""
        ),
        patch.object(
            skill,
            "_collect_life_events",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(
            skill,
            "_collect_upcoming_events",
            new_callable=AsyncMock,
            return_value="",
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "Not enough data" in result.response_text


async def test_execute_with_spending(skill, ctx):
    """Data from collectors triggers LLM synthesis."""
    msg = _msg()

    with (
        patch.object(
            skill,
            "_collect_spending",
            new_callable=AsyncMock,
            return_value=(
                "SPENDING: USD 500 this week (12 transactions)"
                " | vs last week: +15%"
            ),
        ),
        patch.object(
            skill,
            "_collect_spending_by_category",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(
            skill,
            "_collect_completed_tasks",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(
            skill, "_collect_pending_tasks", new_callable=AsyncMock, return_value=""
        ),
        patch.object(
            skill,
            "_collect_life_events",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(
            skill,
            "_collect_upcoming_events",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "src.skills.weekly_digest.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Your Week</b>\nYou spent $500 this week.",
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "Your Week" in result.response_text


async def test_execute_with_multiple_sections(skill, ctx):
    """Multiple data sections are combined and sent to LLM."""
    msg = _msg()

    with (
        patch.object(
            skill,
            "_collect_spending",
            new_callable=AsyncMock,
            return_value="SPENDING: USD 300 this week (8 transactions)",
        ),
        patch.object(
            skill,
            "_collect_spending_by_category",
            new_callable=AsyncMock,
            return_value="TOP CATEGORIES:\n  - Food: USD 150\n  - Transport: USD 100",
        ),
        patch.object(
            skill,
            "_collect_completed_tasks",
            new_callable=AsyncMock,
            return_value="COMPLETED TASKS: 3 tasks done this week",
        ),
        patch.object(
            skill,
            "_collect_pending_tasks",
            new_callable=AsyncMock,
            return_value="PENDING TASKS:\n  - Buy groceries (due: 2026-03-05)",
        ),
        patch.object(
            skill,
            "_collect_life_events",
            new_callable=AsyncMock,
            return_value="LIFE EVENTS:\n  - food: 5\n  - mood: 2",
        ),
        patch.object(
            skill,
            "_collect_upcoming_events",
            new_callable=AsyncMock,
            return_value="UPCOMING (next 7 days):\n  - Meeting (2026-03-03 10:00)",
        ),
        patch(
            "src.skills.weekly_digest.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Your Week</b>\nGreat week with lots of activity!",
        ) as mock_llm,
    ):
        result = await skill.execute(msg, ctx, {})

    assert "Your Week" in result.response_text
    # Verify all sections were passed to LLM
    call_args = mock_llm.call_args
    user_content = call_args.kwargs["messages"][0]["content"]
    assert "SPENDING" in user_content
    assert "TOP CATEGORIES" in user_content
    assert "COMPLETED TASKS" in user_content
    assert "PENDING TASKS" in user_content
    assert "LIFE EVENTS" in user_content
    assert "UPCOMING" in user_content


async def test_collector_exception_handled(skill, ctx):
    """Collector exceptions are handled gracefully."""
    msg = _msg()

    with (
        patch.object(
            skill,
            "_collect_spending",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ),
        patch.object(
            skill,
            "_collect_spending_by_category",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(
            skill,
            "_collect_completed_tasks",
            new_callable=AsyncMock,
            return_value="COMPLETED TASKS: 5 tasks done this week",
        ),
        patch.object(
            skill, "_collect_pending_tasks", new_callable=AsyncMock, return_value=""
        ),
        patch.object(
            skill,
            "_collect_life_events",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(
            skill,
            "_collect_upcoming_events",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "src.skills.weekly_digest.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Your Week</b>\n5 tasks completed!",
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "5 tasks" in result.response_text


async def test_all_collectors_fail(skill, ctx):
    """All collectors failing returns no-data message."""
    msg = _msg()

    with (
        patch.object(
            skill,
            "_collect_spending",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ),
        patch.object(
            skill,
            "_collect_spending_by_category",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ),
        patch.object(
            skill,
            "_collect_completed_tasks",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ),
        patch.object(
            skill,
            "_collect_pending_tasks",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ),
        patch.object(
            skill,
            "_collect_life_events",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ),
        patch.object(
            skill,
            "_collect_upcoming_events",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "Not enough data" in result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt is parameterized with the user's language."""
    ctx_es = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="es",
        currency="EUR",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )
    prompt = skill.get_system_prompt(ctx_es)
    assert "es" in prompt
