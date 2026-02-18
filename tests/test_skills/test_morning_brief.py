"""Tests for morning_brief skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.morning_brief.handler import MorningBriefSkill

MODULE = "src.skills.morning_brief.handler"


@pytest.fixture
def skill():
    return MorningBriefSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="give me my morning brief",
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
async def test_morning_brief_requires_google(skill, message, ctx):
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
async def test_morning_brief_with_data(skill, message, ctx):
    """Generates brief from real email + calendar data."""
    mock_google = AsyncMock()
    mock_google.list_events = AsyncMock(
        return_value=[
            {
                "summary": "Standup",
                "start": {"dateTime": "2026-02-18T09:00:00+00:00"},
            },
        ]
    )
    mock_google.list_messages = AsyncMock(
        return_value=[
            {
                "id": "msg1",
                "threadId": "t1",
                "snippet": "Project update",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Sarah <sarah@test.com>"},
                        {"name": "Subject", "value": "Project deadline"},
                    ]
                },
            }
        ]
    )

    brief = "<b>Доброе утро!</b>\n• 9:00 — Standup\n\n📧 Sarah — Project deadline\n\nУдачного дня!"
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
            f"{MODULE}._generate_brief",
            new_callable=AsyncMock,
            return_value=brief,
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert "утро" in result.response_text.lower() or "Standup" in result.response_text


@pytest.mark.asyncio
async def test_morning_brief_empty_calendar_and_inbox(skill, message, ctx):
    """Handles empty calendar and inbox gracefully."""
    mock_google = AsyncMock()
    mock_google.list_events = AsyncMock(return_value=[])
    mock_google.list_messages = AsyncMock(return_value=[])

    brief = "<b>Доброе утро!</b>\nКалендарь свободен. Нет важных писем."
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
            f"{MODULE}._generate_brief",
            new_callable=AsyncMock,
            return_value=brief,
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
