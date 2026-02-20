"""Tests for price_check skill."""

from unittest.mock import AsyncMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.price_check.handler import PriceCheckSkill


def test_price_check_skill_attributes():
    skill = PriceCheckSkill()
    assert skill.name == "price_check"
    assert "price_check" in skill.intents
    assert skill.model == "gpt-5.2"


def test_price_check_system_prompt(sample_context):
    skill = PriceCheckSkill()
    prompt = skill.get_system_prompt(sample_context)
    assert "price" in prompt.lower()


async def test_price_check_empty_message(sample_context):
    skill = PriceCheckSkill()
    msg = IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text="")
    result = await skill.execute(msg, sample_context, {})
    assert "price" in result.response_text.lower()


async def test_price_check_success(sample_context):
    skill = PriceCheckSkill()
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="2x4 lumber at Home Depot",
    )
    with patch("src.skills.price_check.handler.browser_tool") as mock:
        mock.execute_task = AsyncMock(
            return_value={"success": True, "result": "$4.98 at Home Depot", "steps": 5}
        )
        result = await skill.execute(msg, sample_context, {})
    assert "$4.98" in result.response_text


async def test_price_check_fallback(sample_context):
    skill = PriceCheckSkill()
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="some obscure product",
    )
    with patch("src.skills.price_check.handler.browser_tool") as mock:
        mock.execute_task = AsyncMock(
            return_value={"success": False, "result": "timeout", "steps": 0}
        )
        result = await skill.execute(msg, sample_context, {})
    assert "couldn't" in result.response_text.lower() or "search" in result.response_text.lower()
