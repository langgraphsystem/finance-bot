"""Tests for read_inbox skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.read_inbox.handler import ReadInboxSkill


@pytest.fixture
def skill():
    return ReadInboxSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="check my email",
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
async def test_read_inbox_basic(skill, message, ctx):
    """Returns inbox summary."""
    summary = (
        "<b>Needs reply:</b>\n"
        "1. Sarah — Project deadline moved to Friday\n"
        "2. Boss — Q4 review meeting agenda\n\n"
        "<b>FYI:</b>\n"
        "3. HR — Holiday schedule update\n\n"
        "Need me to reply to any of these?"
    )
    with patch(
        "src.skills.read_inbox.handler.summarize_inbox",
        new_callable=AsyncMock,
        return_value=summary,
    ):
        result = await skill.execute(message, ctx, {})

    assert "Sarah" in result.response_text
    assert "reply" in result.response_text.lower()


@pytest.mark.asyncio
async def test_read_inbox_from_message_text(skill, ctx):
    """Uses message.text for the inbox query."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="any important emails today?",
    )
    with patch(
        "src.skills.read_inbox.handler.summarize_inbox",
        new_callable=AsyncMock,
        return_value="1. Mike — Invoice attached\n\nNeed me to reply to any of these?",
    ) as mock_inbox:
        result = await skill.execute(msg, ctx, {})

    mock_inbox.assert_awaited_once_with("any important emails today?", "en")
    assert "Mike" in result.response_text


@pytest.mark.asyncio
async def test_read_inbox_empty_text(skill, ctx):
    """Empty text defaults to check my email query."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.read_inbox.handler.summarize_inbox",
        new_callable=AsyncMock,
        return_value="No new important emails.",
    ) as mock_inbox:
        result = await skill.execute(msg, ctx, {})

    mock_inbox.assert_awaited_once_with("check my email", "en")
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
