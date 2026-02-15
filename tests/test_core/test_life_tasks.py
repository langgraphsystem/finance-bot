"""Tests for life-tracking cron tasks."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models.enums import LifeEventType

# --- weekly_life_digest ---


@pytest.mark.asyncio
async def test_weekly_digest_skips_users_with_no_events():
    """Weekly digest skips users who have no events in the past week."""
    from src.core.tasks.life_tasks import weekly_life_digest

    mock_users = [("fam-1", "usr-1", 111)]

    with (
        patch(
            "src.core.tasks.life_tasks._get_family_users",
            new_callable=AsyncMock,
            return_value=mock_users,
        ),
        patch(
            "src.core.tasks.life_tasks.query_life_events",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.core.tasks.life_tasks._send_telegram_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await weekly_life_digest()

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_digest_sends_to_users_with_events():
    """Weekly digest is sent to users who have events."""
    from src.core.tasks.life_tasks import weekly_life_digest

    mock_users = [("fam-1", "usr-1", 111)]
    mock_event = MagicMock()
    mock_event.type = LifeEventType.note
    mock_event.data = None
    mock_event.date = date.today()
    mock_event.text = "test note"

    with (
        patch(
            "src.core.tasks.life_tasks._get_family_users",
            new_callable=AsyncMock,
            return_value=mock_users,
        ),
        patch(
            "src.core.tasks.life_tasks.query_life_events",
            new_callable=AsyncMock,
            return_value=[mock_event],
        ),
        patch(
            "src.core.tasks.life_tasks._send_telegram_message",
            new_callable=AsyncMock,
        ) as mock_send,
        patch(
            "src.core.tasks.life_tasks._generate_digest_analysis",
            new_callable=AsyncMock,
            return_value="Some insight",
        ),
        patch(
            "src.core.memory.mem0_client.add_memory",
            new_callable=AsyncMock,
        ),
    ):
        await weekly_life_digest()

    mock_send.assert_awaited_once()
    call_args = mock_send.call_args
    assert call_args[0][0] == 111  # telegram_id
    assert "дайджест" in call_args[0][1].lower()


# --- morning_plan_reminder ---


@pytest.mark.asyncio
async def test_morning_reminder_skips_silent_users():
    """Morning reminder skips users in silent mode."""
    from src.core.tasks.life_tasks import morning_plan_reminder

    mock_users = [("fam-1", "usr-1", 111)]

    with (
        patch(
            "src.core.tasks.life_tasks._get_family_users",
            new_callable=AsyncMock,
            return_value=mock_users,
        ),
        patch(
            "src.core.tasks.life_tasks.query_life_events",
            new_callable=AsyncMock,
            return_value=[],  # no plan
        ),
        patch(
            "src.core.tasks.life_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="silent",
        ),
        patch(
            "src.core.tasks.life_tasks._send_telegram_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await morning_plan_reminder()

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_morning_reminder_skips_users_with_plan():
    """Morning reminder skips users who already have a plan."""
    from src.core.tasks.life_tasks import morning_plan_reminder

    mock_users = [("fam-1", "usr-1", 111)]
    mock_task = MagicMock()
    mock_task.type = LifeEventType.task

    with (
        patch(
            "src.core.tasks.life_tasks._get_family_users",
            new_callable=AsyncMock,
            return_value=mock_users,
        ),
        patch(
            "src.core.tasks.life_tasks.query_life_events",
            new_callable=AsyncMock,
            return_value=[mock_task],  # already has plan
        ),
        patch(
            "src.core.tasks.life_tasks._send_telegram_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await morning_plan_reminder()

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_morning_reminder_sends_to_eligible_users():
    """Morning reminder is sent to non-silent users without a plan."""
    from src.core.tasks.life_tasks import morning_plan_reminder

    mock_users = [("fam-1", "usr-1", 111)]

    with (
        patch(
            "src.core.tasks.life_tasks._get_family_users",
            new_callable=AsyncMock,
            return_value=mock_users,
        ),
        patch(
            "src.core.tasks.life_tasks.query_life_events",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.core.tasks.life_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="receipt",
        ),
        patch(
            "src.core.tasks.life_tasks._send_telegram_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await morning_plan_reminder()

    mock_send.assert_awaited_once()
    call_args = mock_send.call_args
    assert call_args[0][0] == 111
    assert "утро" in call_args[0][1].lower()


# --- evening_reflection_prompt ---


@pytest.mark.asyncio
async def test_evening_reflection_skips_users_with_reflection():
    """Evening prompt skips users who already reflected today."""
    from src.core.tasks.life_tasks import evening_reflection_prompt

    mock_users = [("fam-1", "usr-1", 111)]
    mock_reflection = MagicMock()
    mock_reflection.type = LifeEventType.reflection

    with (
        patch(
            "src.core.tasks.life_tasks._get_family_users",
            new_callable=AsyncMock,
            return_value=mock_users,
        ),
        patch(
            "src.core.tasks.life_tasks.query_life_events",
            new_callable=AsyncMock,
            return_value=[mock_reflection],
        ),
        patch(
            "src.core.tasks.life_tasks._send_telegram_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await evening_reflection_prompt()

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_evening_reflection_skips_silent_users():
    """Evening prompt skips silent users even without reflection."""
    from src.core.tasks.life_tasks import evening_reflection_prompt

    mock_users = [("fam-1", "usr-1", 111)]

    # First call: no reflections; second call: day events
    call_count = 0

    async def _mock_query(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    with (
        patch(
            "src.core.tasks.life_tasks._get_family_users",
            new_callable=AsyncMock,
            return_value=mock_users,
        ),
        patch(
            "src.core.tasks.life_tasks.query_life_events",
            side_effect=_mock_query,
        ),
        patch(
            "src.core.tasks.life_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="silent",
        ),
        patch(
            "src.core.tasks.life_tasks._send_telegram_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await evening_reflection_prompt()

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_evening_reflection_sends_prompt():
    """Evening prompt is sent to eligible users."""
    from src.core.tasks.life_tasks import evening_reflection_prompt

    mock_users = [("fam-1", "usr-1", 111)]

    async def _mock_query(**kwargs):
        return []

    with (
        patch(
            "src.core.tasks.life_tasks._get_family_users",
            new_callable=AsyncMock,
            return_value=mock_users,
        ),
        patch(
            "src.core.tasks.life_tasks.query_life_events",
            side_effect=_mock_query,
        ),
        patch(
            "src.core.tasks.life_tasks.get_communication_mode",
            new_callable=AsyncMock,
            return_value="receipt",
        ),
        patch(
            "src.core.tasks.life_tasks._send_telegram_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await evening_reflection_prompt()

    mock_send.assert_awaited_once()
    call_args = mock_send.call_args
    assert call_args[0][0] == 111
    assert "рефлексии" in call_args[0][1].lower()
