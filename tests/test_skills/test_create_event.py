"""Tests for create_event skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.create_event.handler import CreateEventSkill

MODULE = "src.skills.create_event.handler"

EXTRACT_JSON = (
    '{"title": "Meeting with Sarah", "date": "2026-02-19",'
    ' "time": "15:00", "duration_hours": 1, "location": null}'
)


@pytest.fixture
def skill():
    return CreateEventSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="schedule a meeting with Sarah at 3pm tomorrow",
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
async def test_create_event_requires_google(skill, message, ctx):
    """Returns connect button when Google not connected."""
    from src.skills.base import SkillResult

    prompt = SkillResult(
        response_text="Подключите Google",
        buttons=[
            {"text": "🔗 Подключить Google", "url": "https://example.com"}
        ],
    )
    intent = {"event_title": "Meeting", "event_datetime": "3pm"}
    with patch(
        f"{MODULE}.require_google_or_prompt",
        new_callable=AsyncMock,
        return_value=prompt,
    ):
        result = await skill.execute(message, ctx, intent)

    assert result.buttons


@pytest.mark.asyncio
async def test_create_event_returns_preview_with_buttons(
    skill, message, ctx
):
    """Returns preview + confirm/cancel buttons instead of creating."""
    mock_google = AsyncMock()
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()

    intent = {
        "event_title": "Meeting with Sarah",
        "event_datetime": "3pm",
    }
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
            f"{MODULE}._extract_event_details",
            new_callable=AsyncMock,
            return_value=EXTRACT_JSON,
        ),
        patch("src.core.pending_actions.redis", mock_redis),
    ):
        result = await skill.execute(message, ctx, intent)

    assert "Новое событие" in result.response_text
    assert "Meeting with Sarah" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action" in result.buttons[0]["callback"]
    assert "cancel_action" in result.buttons[1]["callback"]
    # Google API should NOT have been called yet
    mock_google.create_event.assert_not_called()


@pytest.mark.asyncio
async def test_execute_create_event_success():
    """execute_create_event creates event via Calendar API."""
    from src.skills.create_event.handler import execute_create_event

    mock_google = AsyncMock()
    mock_google.create_event = AsyncMock(
        return_value={"htmlLink": "https://cal.google.com/evt/1"}
    )

    action_data = {
        "title": "Meeting",
        "start_iso": "2026-02-19T15:00:00+00:00",
        "end_iso": "2026-02-19T16:00:00+00:00",
        "location": None,
    }

    with patch(
        f"{MODULE}.get_google_client",
        new_callable=AsyncMock,
        return_value=mock_google,
    ):
        result = await execute_create_event(action_data, "user-1")

    assert "Создано" in result
    mock_google.create_event.assert_awaited_once()


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
