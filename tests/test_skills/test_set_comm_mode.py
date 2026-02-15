"""Tests for set_comm_mode skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.set_comm_mode.handler import SetCommModeSkill


@pytest.fixture
def skill():
    return SetCommModeSkill()


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


@pytest.mark.asyncio
async def test_alias_silent(skill, ctx):
    """Alias 'тихий' resolves to silent mode."""
    msg = _msg("тихий режим")

    with patch(
        "src.skills.set_comm_mode.handler.set_communication_mode",
        new_callable=AsyncMock,
    ) as mock_set:
        result = await skill.execute(msg, ctx, {})

    mock_set.assert_awaited_once_with(ctx.user_id, "silent")
    assert "Тихий" in result.response_text
    assert "Готово" in result.response_text


@pytest.mark.asyncio
async def test_alias_coaching(skill, ctx):
    """Alias 'коучинг' resolves to coaching mode."""
    msg = _msg("включи коучинг")

    with patch(
        "src.skills.set_comm_mode.handler.set_communication_mode",
        new_callable=AsyncMock,
    ) as mock_set:
        result = await skill.execute(msg, ctx, {})

    mock_set.assert_awaited_once_with(ctx.user_id, "coaching")
    assert "коучинг" in result.response_text.lower()


@pytest.mark.asyncio
async def test_alias_receipt(skill, ctx):
    """Alias 'квитанция' resolves to receipt mode."""
    msg = _msg("квитанция")

    with patch(
        "src.skills.set_comm_mode.handler.set_communication_mode",
        new_callable=AsyncMock,
    ) as mock_set:
        result = await skill.execute(msg, ctx, {})

    mock_set.assert_awaited_once_with(ctx.user_id, "receipt")
    assert "квитанци" in result.response_text.lower()


@pytest.mark.asyncio
async def test_mode_from_intent_data(skill, ctx):
    """Mode provided via intent_data takes priority."""
    msg = _msg("режим")
    intent_data = {"mode": "coaching"}

    with patch(
        "src.skills.set_comm_mode.handler.set_communication_mode",
        new_callable=AsyncMock,
    ) as mock_set:
        result = await skill.execute(msg, ctx, intent_data)

    mock_set.assert_awaited_once_with(ctx.user_id, "coaching")
    assert "Готово" in result.response_text


@pytest.mark.asyncio
async def test_comm_mode_from_intent_data(skill, ctx):
    """Mode via intent_data 'comm_mode' key works."""
    msg = _msg("режим")
    intent_data = {"comm_mode": "silent"}

    with patch(
        "src.skills.set_comm_mode.handler.set_communication_mode",
        new_callable=AsyncMock,
    ) as mock_set:
        await skill.execute(msg, ctx, intent_data)

    mock_set.assert_awaited_once_with(ctx.user_id, "silent")


@pytest.mark.asyncio
async def test_buttons_returned_when_no_mode_detected(skill, ctx):
    """Buttons are returned when no mode is detected."""
    msg = _msg("режим общения")

    result = await skill.execute(msg, ctx, {})

    assert "Выберите режим" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 3
    callbacks = [b["callback"] for b in result.buttons]
    assert "comm_mode:silent" in callbacks
    assert "comm_mode:receipt" in callbacks
    assert "comm_mode:coaching" in callbacks


@pytest.mark.asyncio
async def test_invalid_mode_shows_buttons(skill, ctx):
    """Invalid mode in intent_data shows selection buttons."""
    msg = _msg("режим")
    intent_data = {"mode": "invalid_mode"}

    result = await skill.execute(msg, ctx, intent_data)

    assert "Выберите режим" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 3


@pytest.mark.asyncio
async def test_alias_molcha(skill, ctx):
    """Alias 'молча' resolves to silent mode."""
    msg = _msg("молча")

    with patch(
        "src.skills.set_comm_mode.handler.set_communication_mode",
        new_callable=AsyncMock,
    ) as mock_set:
        await skill.execute(msg, ctx, {})

    mock_set.assert_awaited_once_with(ctx.user_id, "silent")


@pytest.mark.asyncio
async def test_alias_sovet(skill, ctx):
    """Alias 'совет' resolves to coaching mode."""
    msg = _msg("совет")

    with patch(
        "src.skills.set_comm_mode.handler.set_communication_mode",
        new_callable=AsyncMock,
    ) as mock_set:
        await skill.execute(msg, ctx, {})

    mock_set.assert_awaited_once_with(ctx.user_id, "coaching")
