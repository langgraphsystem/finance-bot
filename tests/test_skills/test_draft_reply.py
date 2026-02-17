"""Tests for draft_reply skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.draft_reply.handler import DraftReplySkill


@pytest.fixture
def skill():
    return DraftReplySkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="reply to Sarah's email saying I'll be there at 3pm",
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
async def test_draft_reply_basic(skill, message, ctx):
    """Returns a drafted email reply."""
    draft = (
        "Hi Sarah,\n\nThanks for the invite! I'll be there at 3 PM.\n\nBest,\nUser\n\nSend this?"
    )
    with patch(
        "src.skills.draft_reply.handler.draft_reply_response",
        new_callable=AsyncMock,
        return_value=draft,
    ):
        result = await skill.execute(message, ctx, {})

    assert "Sarah" in result.response_text
    assert "3 PM" in result.response_text


@pytest.mark.asyncio
async def test_draft_reply_from_message_text(skill, ctx):
    """Uses message.text for the reply query."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="tell Mike I can't make it to the meeting",
    )
    with patch(
        "src.skills.draft_reply.handler.draft_reply_response",
        new_callable=AsyncMock,
        return_value="Hi Mike,\n\nSorry, I won't be able to make it.\n\nSend this?",
    ) as mock_reply:
        result = await skill.execute(msg, ctx, {})

    mock_reply.assert_awaited_once_with("tell Mike I can't make it to the meeting", "en")
    assert "Mike" in result.response_text


@pytest.mark.asyncio
async def test_draft_reply_empty_text(skill, ctx):
    """Empty text passes empty string to handler."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.draft_reply.handler.draft_reply_response",
        new_callable=AsyncMock,
        return_value="Which email would you like to reply to?",
    ) as mock_reply:
        result = await skill.execute(msg, ctx, {})

    mock_reply.assert_awaited_once_with("", "en")
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
