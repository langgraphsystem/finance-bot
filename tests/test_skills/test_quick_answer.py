"""Tests for quick_answer skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.quick_answer.handler import QuickAnswerSkill


@pytest.fixture
def skill():
    return QuickAnswerSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="how many cups in a gallon?",
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
async def test_quick_answer_basic(skill, message, ctx):
    """Returns an answer from LLM."""
    with patch(
        "src.skills.quick_answer.handler.generate_answer",
        new_callable=AsyncMock,
        return_value="16 cups in a gallon (128 oz).",
    ):
        result = await skill.execute(message, ctx, {"search_topic": "cups in a gallon"})

    assert "16 cups" in result.response_text


@pytest.mark.asyncio
async def test_quick_answer_from_message_text(skill, ctx):
    """Falls back to message.text when intent_data has no topic."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="what is the speed of light?",
    )
    with patch(
        "src.skills.quick_answer.handler.generate_answer",
        new_callable=AsyncMock,
        return_value="299,792,458 meters per second.",
    ) as mock_gen:
        result = await skill.execute(msg, ctx, {})

    mock_gen.assert_awaited_once_with("what is the speed of light?", "en")
    assert "299,792,458" in result.response_text


@pytest.mark.asyncio
async def test_quick_answer_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "What would you like to know?" in result.response_text


@pytest.mark.asyncio
async def test_quick_answer_uses_language(skill, message):
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
        "src.skills.quick_answer.handler.generate_answer",
        new_callable=AsyncMock,
        return_value="16 чашек в галлоне.",
    ) as mock_gen:
        await skill.execute(message, ctx, {})

    mock_gen.assert_awaited_once_with("how many cups in a gallon?", "ru")


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
