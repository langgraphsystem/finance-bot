"""Tests for track_food skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import LifeEventType
from src.gateway.types import IncomingMessage, MessageType
from src.skills.track_food.handler import TrackFoodSkill


@pytest.fixture
def skill():
    return TrackFoodSkill()


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
            "src.skills.track_food.handler.save_life_event",
            new_callable=AsyncMock,
        ),
        patch(
            "src.skills.track_food.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value=mode,
        ),
    )


@pytest.mark.asyncio
async def test_food_item_from_intent_data(skill, ctx):
    """Food item is taken from intent_data when provided."""
    msg = _msg("овсянка на завтрак")
    intent_data = {"food_item": "овсянка", "meal_type": "breakfast"}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(msg, ctx, intent_data)

    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["event_type"] == LifeEventType.food
    assert call_kwargs["data"]["food_item"] == "овсянка"
    assert call_kwargs["data"]["meal_type"] == "breakfast"
    assert result.response_text


@pytest.mark.asyncio
async def test_meal_type_alias_zavtrak(skill, ctx):
    """Alias 'завтрак' resolves to 'breakfast'."""
    msg = _msg("овсянка на завтрак")
    intent_data = {"food_item": "овсянка"}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, intent_data)

    data = mock_save.call_args.kwargs["data"]
    assert data["meal_type"] == "breakfast"


@pytest.mark.asyncio
async def test_meal_type_alias_obed(skill, ctx):
    """Alias 'обед' resolves to 'lunch'."""
    msg = _msg("суп на обед")
    intent_data = {"food_item": "суп"}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, intent_data)

    data = mock_save.call_args.kwargs["data"]
    assert data["meal_type"] == "lunch"


@pytest.mark.asyncio
async def test_meal_type_alias_uzhin(skill, ctx):
    """Alias 'ужин' resolves to 'dinner'."""
    msg = _msg("салат на ужин")
    intent_data = {"food_item": "салат"}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, intent_data)

    data = mock_save.call_args.kwargs["data"]
    assert data["meal_type"] == "dinner"


@pytest.mark.asyncio
async def test_meal_type_alias_perekus(skill, ctx):
    """Alias 'перекус' resolves to 'snack'."""
    msg = _msg("яблоко перекус")
    intent_data = {"food_item": "яблоко"}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, intent_data)

    data = mock_save.call_args.kwargs["data"]
    assert data["meal_type"] == "snack"


@pytest.mark.asyncio
async def test_unknown_meal_type_defaults_to_meal(skill, ctx):
    """When no meal alias matches, meal_type defaults to 'meal'."""
    msg = _msg("бургер")
    intent_data = {"food_item": "бургер"}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, intent_data)

    data = mock_save.call_args.kwargs["data"]
    assert data["meal_type"] == "meal"


@pytest.mark.asyncio
async def test_empty_food_returns_prompt(skill, ctx):
    """Empty food item returns a prompt message."""
    msg = _msg("")
    intent_data = {"food_item": ""}
    p_save, p_mode = _patch_helpers()

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, intent_data)

    assert "Что вы ели" in result.response_text


@pytest.mark.asyncio
async def test_no_food_in_intent_uses_message_text(skill, ctx):
    """When no food in intent_data, message text is used."""
    msg = _msg("пицца")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    data = mock_save.call_args.kwargs["data"]
    assert data["food_item"] == "пицца"


@pytest.mark.asyncio
async def test_silent_mode(skill, ctx):
    """Silent mode returns empty response."""
    msg = _msg("каша")
    intent_data = {"food_item": "каша"}
    p_save, p_mode = _patch_helpers(mode="silent")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, intent_data)

    assert result.response_text == ""


@pytest.mark.asyncio
async def test_coaching_mode(skill, ctx):
    """Coaching mode includes a tracking insight."""
    msg = _msg("каша на завтрак")
    intent_data = {"food_item": "каша", "meal_type": "breakfast"}
    p_save, p_mode = _patch_helpers(mode="coaching")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, intent_data)

    assert "\U0001f4a1" in result.response_text
    assert "питания" in result.response_text


@pytest.mark.asyncio
async def test_receipt_mode(skill, ctx):
    """Receipt mode returns formatted receipt without insight."""
    msg = _msg("каша")
    intent_data = {"food_item": "каша", "meal_type": "breakfast"}
    p_save, p_mode = _patch_helpers(mode="receipt")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, intent_data)

    assert result.response_text
    assert "\U0001f4a1" not in result.response_text
