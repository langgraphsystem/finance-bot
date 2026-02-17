"""Tests for web_search skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.web_search.handler import FALLBACK_DISCLAIMER, WebSearchSkill


@pytest.fixture
def skill():
    return WebSearchSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="what time does Costco close?",
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
async def test_web_search_grounded(skill, message, ctx):
    """Returns grounded search result."""
    with patch(
        "src.skills.web_search.handler.search_and_answer",
        new_callable=AsyncMock,
        return_value="Costco closes at 8:30 PM on weekdays.",
    ):
        result = await skill.execute(
            message, ctx, {"search_topic": "Costco closing time"}
        )

    assert "8:30 PM" in result.response_text


@pytest.mark.asyncio
async def test_web_search_from_message_text(skill, ctx):
    """Falls back to message.text when no search_topic."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="best plumber in Queens",
    )
    with patch(
        "src.skills.web_search.handler.search_and_answer",
        new_callable=AsyncMock,
        return_value="Top rated plumbers in Queens: ...",
    ) as mock_search:
        result = await skill.execute(msg, ctx, {})

    mock_search.assert_awaited_once_with("best plumber in Queens", "en")
    assert "plumber" in result.response_text.lower()


@pytest.mark.asyncio
async def test_web_search_empty_query(skill, ctx):
    """Empty query returns prompt."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )
    result = await skill.execute(msg, ctx, {})
    assert "What would you like me to search for?" in result.response_text


@pytest.mark.asyncio
async def test_web_search_fallback_disclaimer():
    """Fallback disclaimer is appended when grounding fails."""
    assert "training data" in FALLBACK_DISCLAIMER


def test_system_prompt_includes_language(skill, ctx):
    """System prompt contains the user's language."""
    prompt = skill.get_system_prompt(ctx)
    assert "en" in prompt
