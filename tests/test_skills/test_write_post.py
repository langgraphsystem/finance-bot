"""Tests for write_post skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.write_post.handler import WritePostSkill


@pytest.fixture
def skill():
    return WritePostSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="write a response to this bad review: customer says we left a mess",
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
async def test_write_post_basic(skill, message, ctx):
    """Returns platform-ready content."""
    response_text = (
        "Thank you for your feedback. We take cleanliness seriously "
        "and I'm sorry we didn't meet your expectations. "
        "Please call us so we can make it right.\n\n"
        "Want me to adjust the tone?"
    )
    with patch(
        "src.skills.write_post.handler.generate_post",
        new_callable=AsyncMock,
        return_value=response_text,
    ):
        result = await skill.execute(
            message, ctx, {"writing_topic": "respond to bad review about mess"}
        )

    assert "feedback" in result.response_text
    assert "cleanliness" in result.response_text


@pytest.mark.asyncio
async def test_write_post_with_platform(skill, ctx):
    """Platform is prepended to the topic."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="write an Instagram caption about our new project",
    )
    with patch(
        "src.skills.write_post.handler.generate_post",
        new_callable=AsyncMock,
        return_value="New project alert! Fresh bathroom remodel just completed.",
    ) as mock_gen:
        result = await skill.execute(
            msg, ctx, {
                "writing_topic": "new project completed",
                "target_platform": "instagram",
            }
        )

    # Platform should be prepended to the topic
    call_args = mock_gen.call_args
    assert "instagram" in call_args[0][0].lower()
    assert "project" in result.response_text.lower()


@pytest.mark.asyncio
async def test_write_post_from_message_text(skill, ctx):
    """Falls back to message.text when no writing_topic."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="write a Google review response thanking the customer",
    )
    with patch(
        "src.skills.write_post.handler.generate_post",
        new_callable=AsyncMock,
        return_value="Thank you for the kind words! We appreciate your business.",
    ) as mock_gen:
        result = await skill.execute(msg, ctx, {})

    mock_gen.assert_awaited_once_with(
        "write a Google review response thanking the customer", "en"
    )
    assert "Thank you" in result.response_text


@pytest.mark.asyncio
async def test_write_post_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "What would you like me to write?" in result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
