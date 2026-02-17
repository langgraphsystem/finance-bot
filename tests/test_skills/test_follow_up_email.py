"""Tests for follow_up_email skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.follow_up_email.handler import FollowUpEmailSkill


@pytest.fixture
def skill():
    return FollowUpEmailSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="any emails I haven't replied to?",
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
async def test_follow_up_basic(skill, message, ctx):
    """Returns list of unanswered emails."""
    follow_ups = (
        "Sarah — Project deadline (received 2 days ago)\n"
        "Boss — Q4 review (received 1 day ago)\n\n"
        "Want me to draft a reply to any of these?"
    )
    with patch(
        "src.skills.follow_up_email.handler.check_follow_ups",
        new_callable=AsyncMock,
        return_value=follow_ups,
    ):
        result = await skill.execute(message, ctx, {})

    assert "Sarah" in result.response_text
    assert "draft" in result.response_text.lower()


@pytest.mark.asyncio
async def test_follow_up_from_message_text(skill, ctx):
    """Uses message.text for the follow-up query."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="do I owe anyone a reply?",
    )
    with patch(
        "src.skills.follow_up_email.handler.check_follow_ups",
        new_callable=AsyncMock,
        return_value="You're all caught up — no pending replies.",
    ) as mock_follow:
        result = await skill.execute(msg, ctx, {})

    mock_follow.assert_awaited_once_with("do I owe anyone a reply?", "en")
    assert "caught up" in result.response_text.lower()


@pytest.mark.asyncio
async def test_follow_up_empty_text(skill, ctx):
    """Empty text defaults to follow-up query."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.follow_up_email.handler.check_follow_ups",
        new_callable=AsyncMock,
        return_value="You're all caught up — no pending replies.",
    ) as mock_follow:
        result = await skill.execute(msg, ctx, {})

    mock_follow.assert_awaited_once_with("any emails I need to reply to?", "en")
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
