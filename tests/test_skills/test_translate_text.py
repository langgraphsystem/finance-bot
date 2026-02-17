"""Tests for translate_text skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.translate_text.handler import TranslateTextSkill


@pytest.fixture
def skill():
    return TranslateTextSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="translate this to Spanish: Emma has a dentist appointment tomorrow",
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
async def test_translate_basic(skill, message, ctx):
    """Returns a translation."""
    with patch(
        "src.skills.translate_text.handler.generate_translation",
        new_callable=AsyncMock,
        return_value="Emma tiene una cita con el dentista mañana",
    ):
        result = await skill.execute(
            message,
            ctx,
            {
                "writing_topic": "Emma has a dentist appointment tomorrow",
                "target_language": "Spanish",
            },
        )

    assert "Emma" in result.response_text
    assert "dentista" in result.response_text


@pytest.mark.asyncio
async def test_translate_from_message_text(skill, ctx):
    """Falls back to message.text when no writing_topic."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Good morning, how are you?",
    )
    with patch(
        "src.skills.translate_text.handler.generate_translation",
        new_callable=AsyncMock,
        return_value="Buenos días, ¿cómo estás?",
    ) as mock_gen:
        result = await skill.execute(msg, ctx, {"target_language": "Spanish"})

    mock_gen.assert_awaited_once_with("Good morning, how are you?", "Spanish", "en")
    assert "Buenos" in result.response_text


@pytest.mark.asyncio
async def test_translate_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "What would you like me to translate?" in result.response_text


@pytest.mark.asyncio
async def test_translate_uses_context_language_as_default(skill):
    """Uses context.language as default target when no target_language."""
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
    msg = IncomingMessage(
        id="msg-4",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Hello world",
    )
    with patch(
        "src.skills.translate_text.handler.generate_translation",
        new_callable=AsyncMock,
        return_value="Привет мир",
    ) as mock_gen:
        result = await skill.execute(msg, ctx, {})

    mock_gen.assert_awaited_once_with("Hello world", "ru", "ru")
    assert "Привет" in result.response_text


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
