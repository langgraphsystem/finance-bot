"""Tests for proofread skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.proofread.handler import ProofreadSkill


@pytest.fixture
def skill():
    return ProofreadSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Were coming to fix the pipe tommorrow between 10-12, make sure someone is home",
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
async def test_proofread_basic(skill, message, ctx):
    """Returns corrected text with explanations."""
    corrected = (
        '"We\'re coming to fix the pipe tomorrow between 10-12. '
        'Make sure someone is home."\n\n'
        "• Were → We're (contraction)\n"
        "• tommorrow → tomorrow (spelling)\n"
        "• Added period between sentences"
    )
    with patch(
        "src.skills.proofread.handler.check_text",
        new_callable=AsyncMock,
        return_value=corrected,
    ):
        result = await skill.execute(message, ctx, {})

    assert "We're" in result.response_text
    assert "tomorrow" in result.response_text


@pytest.mark.asyncio
async def test_proofread_from_writing_topic(skill, ctx):
    """Uses writing_topic from intent_data."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="proofread this",
    )
    with patch(
        "src.skills.proofread.handler.check_text",
        new_callable=AsyncMock,
        return_value="Looks good — no changes needed.",
    ) as mock_check:
        result = await skill.execute(
            msg, ctx, {"writing_topic": "The project is complete and ready for review."}
        )

    mock_check.assert_awaited_once_with(
        "The project is complete and ready for review.", "en"
    )
    assert "no changes needed" in result.response_text


@pytest.mark.asyncio
async def test_proofread_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "Send me the text" in result.response_text


@pytest.mark.asyncio
async def test_proofread_uses_language(skill, message):
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
        "src.skills.proofread.handler.check_text",
        new_callable=AsyncMock,
        return_value="Исправлено: We're coming...",
    ) as mock_check:
        await skill.execute(message, ctx, {})

    mock_check.assert_awaited_once_with(
        "Were coming to fix the pipe tommorrow between 10-12, "
        "make sure someone is home",
        "ru",
    )


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
