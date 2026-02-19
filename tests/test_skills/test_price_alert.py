"""Tests for price_alert skill."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.price_alert.handler import PriceAlertSkill


def test_price_alert_skill_attributes():
    skill = PriceAlertSkill()
    assert skill.name == "price_alert"
    assert "price_alert" in skill.intents
    assert skill.model == "claude-haiku-4-5"


def test_price_alert_system_prompt(sample_context):
    skill = PriceAlertSkill()
    prompt = skill.get_system_prompt(sample_context)
    assert "price" in prompt.lower()


async def test_price_alert_empty_message(sample_context):
    skill = PriceAlertSkill()
    msg = IncomingMessage(id="1", user_id="u1", chat_id="c1", type=MessageType.text, text="")
    result = await skill.execute(msg, sample_context, {})
    assert "price" in result.response_text.lower() or "alert" in result.response_text.lower()


async def test_price_alert_creates_monitor(sample_context):
    skill = PriceAlertSkill()
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="Alert me when 2x4 lumber drops below $5 at Home Depot",
    )

    # Mock LLM extraction
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text=json.dumps(
                {
                    "product": "2x4 lumber",
                    "target_price": 5.00,
                    "store": "Home Depot",
                    "direction": "below",
                }
            )
        )
    ]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    with (
        patch("src.skills.price_alert.handler.anthropic_client", return_value=mock_client),
        patch("src.skills.price_alert.handler.async_session", return_value=mock_session),
    ):
        result = await skill.execute(msg, sample_context, {})

    assert "2x4 lumber" in result.response_text
    assert "Home Depot" in result.response_text
    mock_session.add.assert_called_once()


async def test_price_alert_handles_parse_error(sample_context):
    skill = PriceAlertSkill()
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="alert something",
    )

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(side_effect=ValueError("bad json"))

    with patch("src.skills.price_alert.handler.anthropic_client", return_value=mock_client):
        result = await skill.execute(msg, sample_context, {})

    assert "couldn't" in result.response_text.lower() or "try" in result.response_text.lower()
