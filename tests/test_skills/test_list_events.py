"""Tests for list_events skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.list_events.handler import ListEventsSkill


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
async def test_list_events_basic(skill, message, ctx):
    """Returns formatted calendar events."""
    formatted = (
        "• 9:00 AM — Team standup\n"
        "• 12:00 PM — Lunch with Mike\n"
        "• 3:00 PM — Dentist appointment\n\n"
        "Want to schedule something?"
    )
    with patch(
        "src.skills.list_events.handler.format_events",
        new_callable=AsyncMock,
        return_value=formatted,
    ):
        result = await skill.execute(message, ctx, {})

    assert "standup" in result.response_text
    assert "schedule" in result.response_text.lower()


@pytest.mark.asyncio
async def test_list_events_from_message_text(skill, ctx):
    """Falls back to message.text when no specific query."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="what do I have on Friday?",
    )
    with patch(
        "src.skills.list_events.handler.format_events",
        new_callable=AsyncMock,
        return_value="Your calendar is clear on Friday. Want to schedule something?",
    ) as mock_fmt:
        result = await skill.execute(msg, ctx, {})

    mock_fmt.assert_awaited_once_with("what do I have on Friday?", "en")
    assert "Friday" in result.response_text


@pytest.mark.asyncio
async def test_list_events_empty_text(skill, ctx):
    """Empty text defaults to today's schedule query."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.list_events.handler.format_events",
        new_callable=AsyncMock,
        return_value="Your calendar is clear.",
    ) as mock_fmt:
        result = await skill.execute(msg, ctx, {})

    mock_fmt.assert_awaited_once_with("today's schedule", "en")
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
