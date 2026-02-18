"""Tests for list_events skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.list_events.handler import ListEventsSkill

MODULE = "src.skills.list_events.handler"


@pytest.fixture
def skill():
    return ListEventsSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="show me my schedule for tomorrow",
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
async def test_list_events_requires_google(skill, message, ctx):
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
async def test_list_events_no_events(skill, message, ctx):
    """Returns empty calendar message."""
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

    assert "свободен" in result.response_text.lower()


@pytest.mark.asyncio
async def test_list_events_with_events(skill, message, ctx):
    """Formats real calendar events."""
    mock_google = AsyncMock()
    mock_google.list_events = AsyncMock(
        return_value=[
            {
                "summary": "Team standup",
                "start": {"dateTime": "2026-02-18T09:00:00-05:00"},
            },
            {
                "summary": "Lunch",
                "start": {"dateTime": "2026-02-18T12:00:00-05:00"},
            },
        ]
    )

    formatted = "• 9:00 AM — Team standup\n• 12:00 PM — Lunch"
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
            f"{MODULE}._format_events",
            new_callable=AsyncMock,
            return_value=formatted,
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert "standup" in result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
