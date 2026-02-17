"""Tests for morning_brief skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.morning_brief.handler import MorningBriefSkill


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
async def test_morning_brief_basic(skill, message, ctx):
    """Returns a morning summary."""
    brief = (
        "<b>Morning!</b>\n\n"
        "• 9:00 AM — Team standup\n"
        "• 11:00 AM — Client call\n\n"
        "Tasks due today:\n"
        "• Submit expense report\n\n"
        "Suggestion: Block 30 min for the expense report before standup."
    )
    with patch(
        "src.skills.morning_brief.handler.generate_brief",
        new_callable=AsyncMock,
        return_value=brief,
    ):
        result = await skill.execute(message, ctx, {})

    assert "Morning" in result.response_text
    assert "standup" in result.response_text


@pytest.mark.asyncio
async def test_morning_brief_from_message_text(skill, ctx):
    """Uses message.text for the brief query."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="what's on my plate today?",
    )
    with patch(
        "src.skills.morning_brief.handler.generate_brief",
        new_callable=AsyncMock,
        return_value="Morning! No events today — your calendar is clear.",
    ) as mock_brief:
        result = await skill.execute(msg, ctx, {})

    mock_brief.assert_awaited_once_with("what's on my plate today?", "en")
    assert "clear" in result.response_text.lower()


@pytest.mark.asyncio
async def test_morning_brief_empty_text(skill, ctx):
    """Empty text defaults to morning brief query."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.morning_brief.handler.generate_brief",
        new_callable=AsyncMock,
        return_value="Morning! No events today.",
    ) as mock_brief:
        result = await skill.execute(msg, ctx, {})

    mock_brief.assert_awaited_once_with("morning brief", "en")
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
