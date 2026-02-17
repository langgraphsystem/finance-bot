"""Tests for draft_message skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.draft_message.handler import DraftMessageSkill


@pytest.fixture
def skill():
    return DraftMessageSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="write an email to school about Emma being late tomorrow",
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
async def test_draft_basic(skill, message, ctx):
    """Returns a drafted message."""
    draft = (
        "Subject: Emma Rodriguez — Late Arrival Tomorrow\n\n"
        "Dear Teacher,\n\n"
        "Emma will arrive late tomorrow due to a dentist appointment.\n\n"
        "Thank you,\nMaria\n\nWant me to change anything?"
    )
    with patch(
        "src.skills.draft_message.handler.generate_draft",
        new_callable=AsyncMock,
        return_value=draft,
    ):
        result = await skill.execute(
            message, ctx, {"writing_topic": "email to school about Emma being late"}
        )

    assert "Emma" in result.response_text
    assert "late" in result.response_text.lower()


@pytest.mark.asyncio
async def test_draft_from_message_text(skill, ctx):
    """Falls back to message.text when no writing_topic."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="draft a text to Mike about tomorrow's schedule",
    )
    with patch(
        "src.skills.draft_message.handler.generate_draft",
        new_callable=AsyncMock,
        return_value="Hey Mike, just a heads up about tomorrow's schedule.",
    ) as mock_gen:
        result = await skill.execute(msg, ctx, {})

    mock_gen.assert_awaited_once_with("draft a text to Mike about tomorrow's schedule", "en")
    assert "Mike" in result.response_text


@pytest.mark.asyncio
async def test_draft_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "What would you like me to write?" in result.response_text


@pytest.mark.asyncio
async def test_draft_uses_language(skill, message):
    """Language is passed from context."""
    ctx = SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )
    with patch(
        "src.skills.draft_message.handler.generate_draft",
        new_callable=AsyncMock,
        return_value="Тема: Опоздание Эммы завтра",
    ) as mock_gen:
        await skill.execute(message, ctx, {})

    mock_gen.assert_awaited_once_with(
        "write an email to school about Emma being late tomorrow", "ru"
    )


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
