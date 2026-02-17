"""Tests for create_event skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.create_event.handler import CreateEventSkill


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
async def test_create_event_basic(skill, message, ctx):
    """Returns event creation confirmation."""
    confirmation = "Created: <b>Meeting with Sarah</b> — Tomorrow 3:00 PM. 1 hour.\n\nThat work?"
    with patch(
        "src.skills.create_event.handler.create_event_response",
        new_callable=AsyncMock,
        return_value=confirmation,
    ):
        result = await skill.execute(
            message, ctx, {"event_title": "Meeting with Sarah", "event_datetime": "3pm tomorrow"}
        )

    assert "Sarah" in result.response_text
    assert "That work?" in result.response_text


@pytest.mark.asyncio
async def test_create_event_with_intent_data(skill, ctx):
    """Uses event_title and event_datetime from intent_data."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="add dentist appointment Wednesday 10am",
    )
    with patch(
        "src.skills.create_event.handler.create_event_response",
        new_callable=AsyncMock,
        return_value="Created: <b>Dentist</b> — Wednesday 10:00 AM. 1 hour.\n\nThat work?",
    ) as mock_create:
        result = await skill.execute(
            msg, ctx, {"event_title": "Dentist", "event_datetime": "Wednesday 10am"}
        )

    call_args = mock_create.call_args[0][0]
    assert "Dentist" in call_args
    assert "Wednesday 10am" in call_args
    assert "Dentist" in result.response_text


@pytest.mark.asyncio
async def test_create_event_empty_text(skill, ctx):
    """Empty text still builds prompt from intent_data."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.create_event.handler.create_event_response",
        new_callable=AsyncMock,
        return_value="What event would you like to create?",
    ) as mock_create:
        result = await skill.execute(msg, ctx, {})

    mock_create.assert_awaited_once()
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
