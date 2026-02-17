"""Tests for find_free_slots skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.find_free_slots.handler import FindFreeSlotsSkill


@pytest.fixture
def skill():
    return FindFreeSlotsSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="when am I free tomorrow?",
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
async def test_find_free_slots_basic(skill, message, ctx):
    """Returns available time slots."""
    slots = "You're free: 8:00 AM — 10:00 AM, 1:00 PM — 3:00 PM.\n\nWant to book something?"
    with patch(
        "src.skills.find_free_slots.handler.find_free_response",
        new_callable=AsyncMock,
        return_value=slots,
    ):
        result = await skill.execute(message, ctx, {})

    assert "free" in result.response_text.lower()
    assert "book" in result.response_text.lower()


@pytest.mark.asyncio
async def test_find_free_slots_from_message_text(skill, ctx):
    """Uses message.text for the query."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="do I have any gaps on Wednesday afternoon?",
    )
    with patch(
        "src.skills.find_free_slots.handler.find_free_response",
        new_callable=AsyncMock,
        return_value="You're free: 2:00 PM — 6:00 PM on Wednesday.",
    ) as mock_free:
        result = await skill.execute(msg, ctx, {})

    mock_free.assert_awaited_once_with("do I have any gaps on Wednesday afternoon?", "en")
    assert "Wednesday" in result.response_text


@pytest.mark.asyncio
async def test_find_free_slots_empty_text(skill, ctx):
    """Empty text defaults to week availability query."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.find_free_slots.handler.find_free_response",
        new_callable=AsyncMock,
        return_value="You're free all day tomorrow.",
    ) as mock_free:
        result = await skill.execute(msg, ctx, {})

    mock_free.assert_awaited_once_with("when am I free this week?", "en")
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
