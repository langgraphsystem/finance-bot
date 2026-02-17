"""Tests for summarize_thread skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.summarize_thread.handler import SummarizeThreadSkill


@pytest.fixture
def skill():
    return SummarizeThreadSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="summarize the thread with Sarah about the budget",
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
async def test_summarize_thread_basic(skill, message, ctx):
    """Returns thread summary."""
    summary = (
        "<b>Budget discussion with Sarah</b>\n\n"
        "Sarah proposed increasing the Q1 budget by 15%. "
        "You agreed but asked to cap contractor spend.\n\n"
        "Action items:\n"
        "• Sarah to send revised numbers by Friday.\n\n"
        "Any action needed on this?"
    )
    with patch(
        "src.skills.summarize_thread.handler.summarize_thread",
        new_callable=AsyncMock,
        return_value=summary,
    ):
        result = await skill.execute(message, ctx, {})

    assert "Sarah" in result.response_text
    assert "budget" in result.response_text.lower()


@pytest.mark.asyncio
async def test_summarize_thread_from_message_text(skill, ctx):
    """Uses message.text for the thread query."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="what was the email chain with Mike about?",
    )
    with patch(
        "src.skills.summarize_thread.handler.summarize_thread",
        new_callable=AsyncMock,
        return_value="Mike discussed the new hire timeline. Any action needed on this?",
    ) as mock_summarize:
        result = await skill.execute(msg, ctx, {})

    mock_summarize.assert_awaited_once_with("what was the email chain with Mike about?", "en")
    assert "Mike" in result.response_text


@pytest.mark.asyncio
async def test_summarize_thread_empty_text(skill, ctx):
    """Empty text defaults to generic summarize query."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    with patch(
        "src.skills.summarize_thread.handler.summarize_thread",
        new_callable=AsyncMock,
        return_value="Which thread would you like me to summarize?",
    ) as mock_summarize:
        result = await skill.execute(msg, ctx, {})

    mock_summarize.assert_awaited_once_with("summarize this email thread", "en")
    assert result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
