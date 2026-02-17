"""Tests for reschedule_event skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.reschedule_event.handler import RescheduleEventSkill


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
async def test_reschedule_basic(skill, message, ctx):
    """Returns reschedule confirmation."""
    confirmation = "Moved <b>Dentist appointment</b> to Thursday 2:00 PM. No conflicts."
    with patch(
        "src.skills.reschedule_event.handler.reschedule_response",
        new_callable=AsyncMock,
        return_value=confirmation,
    ):
        result = await skill.execute(message, ctx, {})

    assert "Dentist" in result.response_text
    assert "Thursday" in result.response_text


@pytest.mark.asyncio
async def test_reschedule_from_message_text(skill, ctx):
    """Uses message.text for the reschedule query."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="push standup to 10am",
    )
    with patch(
        "src.skills.reschedule_event.handler.reschedule_response",
        new_callable=AsyncMock,
        return_value="Moved <b>Standup</b> to 10:00 AM. No conflicts.",
    ) as mock_resched:
        result = await skill.execute(msg, ctx, {})

    mock_resched.assert_awaited_once_with("push standup to 10am", "en")
    assert "Standup" in result.response_text


@pytest.mark.asyncio
async def test_reschedule_empty_text(skill, ctx):
    """Empty text passes empty string to handler."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.reschedule_event.handler.reschedule_response",
        new_callable=AsyncMock,
        return_value="Which event would you like to reschedule?",
    ) as mock_resched:
        result = await skill.execute(msg, ctx, {})

    mock_resched.assert_awaited_once_with("", "en")
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
