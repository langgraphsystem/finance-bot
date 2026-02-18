"""Tests for reschedule_event skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.reschedule_event.handler import RescheduleEventSkill

MODULE = "src.skills.reschedule_event.handler"


@pytest.fixture
def skill():
    return RescheduleEventSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="move my dentist appointment to Thursday at 2pm",
    )


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


@pytest.mark.asyncio
async def test_reschedule_requires_google(skill, message, ctx):
    """Returns connect button when Google not connected."""
    from src.skills.base import SkillResult

    prompt = SkillResult(
        response_text="Подключите Google",
        buttons=[{"text": "🔗 Подключить Google", "url": "https://example.com"}],
    )
    with patch(
        f"{MODULE}.require_google_or_prompt",
        new_callable=AsyncMock,
        return_value=prompt,
    ):
        result = await skill.execute(message, ctx, {})

    assert result.buttons


@pytest.mark.asyncio
async def test_reschedule_no_events(skill, message, ctx):
    """Returns message when no upcoming events."""
    mock_google = AsyncMock()
    mock_google.list_events = AsyncMock(return_value=[])

    with (
        patch(
            f"{MODULE}.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            f"{MODULE}.get_google_client",
            new_callable=AsyncMock,
            return_value=mock_google,
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert "нет" in result.response_text.lower() or "событий" in result.response_text.lower()


@pytest.mark.asyncio
async def test_reschedule_returns_preview_with_buttons(skill, message, ctx):
    """Returns preview + confirm/cancel buttons instead of updating."""
    mock_google = AsyncMock()
    mock_google.list_events = AsyncMock(
        return_value=[
            {
                "id": "evt1",
                "summary": "Dentist",
                "start": {"dateTime": "2026-02-18T10:00:00+00:00"},
            },
        ]
    )
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()

    reschedule_json = (
        '{"event_id": "evt1", "event_name": "Dentist",'
        ' "new_date": "2026-02-20", "new_time": "14:00"}'
    )
    with (
        patch(
            f"{MODULE}.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            f"{MODULE}.get_google_client",
            new_callable=AsyncMock,
            return_value=mock_google,
        ),
        patch(
            f"{MODULE}._parse_reschedule",
            new_callable=AsyncMock,
            return_value=reschedule_json,
        ),
        patch("src.core.pending_actions.redis", mock_redis),
    ):
        result = await skill.execute(message, ctx, {})

    assert "Перенести событие" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action" in result.buttons[0]["callback"]
    # Google API should NOT have been called yet
    mock_google.update_event.assert_not_called()


@pytest.mark.asyncio
async def test_execute_reschedule_success():
    """execute_reschedule updates event via Calendar API."""
    from src.skills.reschedule_event.handler import execute_reschedule

    mock_google = AsyncMock()
    mock_google.update_event = AsyncMock(return_value={})

    action_data = {
        "event_id": "evt1",
        "event_name": "Dentist",
        "new_date": "2026-02-20",
        "new_time": "14:00",
    }

    with patch(
        f"{MODULE}.get_google_client",
        new_callable=AsyncMock,
        return_value=mock_google,
    ):
        result = await execute_reschedule(action_data, "user-1")

    assert "перенесено" in result.lower()
    mock_google.update_event.assert_awaited_once()


def test_system_prompt_is_string(skill, ctx):
    """System prompt returns the reschedule prompt."""
    prompt = skill.get_system_prompt(ctx)
    assert "reschedule" in prompt.lower() or "JSON" in prompt
