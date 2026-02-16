"""Tests for track_drink skill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import LifeEventType
from src.gateway.types import IncomingMessage, MessageType
from src.skills.track_drink.handler import TrackDrinkSkill


@pytest.fixture
def skill():
    return TrackDrinkSkill()


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="trucker",
        categories=[],
        merchant_mappings=[],
    )


def _msg(text: str) -> IncomingMessage:
    """Create an IncomingMessage with given text."""
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text=text,
    )


def _patch_helpers(mode: str = "receipt"):
    """Patch save_life_event and get_communication_mode."""
    return (
        patch(
            "src.skills.track_drink.handler.save_life_event",
            new_callable=AsyncMock,
        ),
        patch(
            "src.skills.track_drink.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value=mode,
        ),
    )


@pytest.mark.asyncio
async def test_keyword_coffee_detected(skill, ctx):
    """Keyword 'кофе' resolves to 'coffee'."""
    msg = _msg("выпил кофе")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["event_type"] == LifeEventType.drink
    assert "coffee" in call_kwargs["text"]
    assert result.response_text


@pytest.mark.asyncio
async def test_keyword_water_detected(skill, ctx):
    """Keyword 'вода' resolves to 'water'."""
    msg = _msg("вода")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert "water" in mock_save.call_args.kwargs["text"]
    assert result.response_text


@pytest.mark.asyncio
async def test_keyword_tea_detected(skill, ctx):
    """Keyword 'чай' resolves to 'tea'."""
    msg = _msg("зелёный чай")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    assert "tea" in mock_save.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_count_from_intent_data(skill, ctx):
    """Count is extracted from intent_data."""
    msg = _msg("2 кофе")
    intent_data = {"count": 2}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, intent_data)

    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["data"]["count"] == 2
    assert "x2" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_default_volume_coffee(skill, ctx):
    """Default volume for coffee is 250 ml."""
    msg = _msg("кофе")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    data = mock_save.call_args.kwargs["data"]
    assert data["volume_ml"] == 250


@pytest.mark.asyncio
async def test_default_volume_tea(skill, ctx):
    """Default volume for tea is 200 ml."""
    msg = _msg("чай")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    data = mock_save.call_args.kwargs["data"]
    assert data["volume_ml"] == 200


@pytest.mark.asyncio
async def test_default_volume_water(skill, ctx):
    """Default volume for water is 330 ml."""
    msg = _msg("вода")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    data = mock_save.call_args.kwargs["data"]
    assert data["volume_ml"] == 330


@pytest.mark.asyncio
async def test_silent_mode(skill, ctx):
    """Silent mode returns empty response."""
    msg = _msg("кофе")
    p_save, p_mode = _patch_helpers(mode="silent")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert result.response_text == ""


@pytest.mark.asyncio
async def test_receipt_mode(skill, ctx):
    """Receipt mode returns a formatted receipt."""
    msg = _msg("кофе")
    p_save, p_mode = _patch_helpers(mode="receipt")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert result.response_text
    # Receipt should not contain coaching insight
    assert "\U0001f4a1" not in result.response_text


@pytest.mark.asyncio
async def test_coaching_mode(skill, ctx):
    """Coaching mode includes a hydration insight."""
    msg = _msg("кофе")
    p_save, p_mode = _patch_helpers(mode="coaching")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert "\U0001f4a1" in result.response_text
    assert "мл" in result.response_text


@pytest.mark.asyncio
async def test_llm_fallback_when_no_keyword(skill, ctx):
    """LLM fallback is triggered when no keyword matches."""
    msg = _msg("какой-то напиток")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"item": "juice", "volume_ml": 200, "count": 1}')]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    p_save, p_mode = _patch_helpers()

    with (
        p_save as mock_save,
        p_mode,
        patch(
            "src.skills.track_drink.handler.anthropic_client",
            return_value=mock_client,
        ),
    ):
        await skill.execute(msg, ctx, {})

    data = mock_save.call_args.kwargs["data"]
    assert data["item"] == "juice"
    assert data["volume_ml"] == 200


@pytest.mark.asyncio
async def test_llm_fallback_error_defaults_to_drink(skill, ctx):
    """When LLM fallback fails, item defaults to 'drink'."""
    msg = _msg("что-то непонятное")

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API error"))

    p_save, p_mode = _patch_helpers()

    with (
        p_save as mock_save,
        p_mode,
        patch(
            "src.skills.track_drink.handler.anthropic_client",
            return_value=mock_client,
        ),
    ):
        await skill.execute(msg, ctx, {})

    data = mock_save.call_args.kwargs["data"]
    assert data["item"] == "drink"
