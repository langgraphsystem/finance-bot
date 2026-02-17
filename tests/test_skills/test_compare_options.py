"""Tests for compare_options skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.compare_options.handler import CompareOptionsSkill


@pytest.fixture
def skill():
    return CompareOptionsSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="compare PEX vs copper pipe",
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
async def test_compare_basic(skill, message, ctx):
    """Returns a structured comparison."""
    comparison = (
        "<b>PEX vs Copper:</b>\n"
        "• Cost: PEX $0.40-$0.80/ft, Copper $2-$4/ft\n"
        "• Durability: Copper 50+ years, PEX 25-50 years"
    )
    with patch(
        "src.skills.compare_options.handler.generate_comparison",
        new_callable=AsyncMock,
        return_value=comparison,
    ):
        result = await skill.execute(
            message, ctx, {"search_topic": "PEX vs copper pipe"}
        )

    assert "PEX" in result.response_text
    assert "Copper" in result.response_text


@pytest.mark.asyncio
async def test_compare_from_message_text(skill, ctx):
    """Falls back to message.text when no search_topic."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="Costco vs Sam's Club",
    )
    with patch(
        "src.skills.compare_options.handler.generate_comparison",
        new_callable=AsyncMock,
        return_value="Costco: better quality. Sam's: lower price.",
    ) as mock_gen:
        result = await skill.execute(msg, ctx, {})

    mock_gen.assert_awaited_once_with("Costco vs Sam's Club", "en")
    assert "Costco" in result.response_text


@pytest.mark.asyncio
async def test_compare_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "What would you like me to compare?" in result.response_text


@pytest.mark.asyncio
async def test_compare_uses_language(skill, message):
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
        "src.skills.compare_options.handler.generate_comparison",
        new_callable=AsyncMock,
        return_value="PEX дешевле, медь долговечнее.",
    ) as mock_gen:
        await skill.execute(message, ctx, {})

    mock_gen.assert_awaited_once_with("compare PEX vs copper pipe", "ru")


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
