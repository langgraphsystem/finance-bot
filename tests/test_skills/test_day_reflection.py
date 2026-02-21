"""Tests for day_reflection skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import LifeEventType
from src.gateway.types import IncomingMessage, MessageType
from src.skills.day_reflection.handler import DayReflectionSkill


@pytest.fixture
def skill():
    return DayReflectionSkill()


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
            "src.skills.day_reflection.handler.save_life_event",
            new_callable=AsyncMock,
        ),
        patch(
            "src.skills.day_reflection.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value=mode,
        ),
    )


@pytest.mark.asyncio
async def test_bare_trigger_returns_guiding_question(skill, ctx):
    """Bare trigger word 'рефлексия' returns a guiding question."""
    msg = _msg("рефлексия")

    result = await skill.execute(msg, ctx, {})

    assert "Рефлексия дня" in result.response_text
    assert "Что получилось" in result.response_text


@pytest.mark.asyncio
async def test_bare_trigger_itogi_dnya(skill, ctx):
    """Bare trigger 'итоги дня' returns a guiding question."""
    msg = _msg("итоги дня")

    result = await skill.execute(msg, ctx, {})

    assert "Рефлексия дня" in result.response_text


@pytest.mark.asyncio
async def test_bare_trigger_dnevnik(skill, ctx):
    """Bare trigger 'дневник' returns a guiding question."""
    msg = _msg("дневник")

    result = await skill.execute(msg, ctx, {})

    assert "Что получилось" in result.response_text


@pytest.mark.asyncio
async def test_empty_text_returns_guiding_question(skill, ctx):
    """Empty message text returns a guiding question."""
    msg = _msg("")

    result = await skill.execute(msg, ctx, {})

    assert "Рефлексия дня" in result.response_text


@pytest.mark.asyncio
async def test_actual_reflection_text_saved(skill, ctx):
    """Actual reflection text is saved as a life event."""
    reflection = "Сегодня сделал 3 задачи из 5, неплохо"
    msg = _msg(reflection)
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    mock_save.assert_awaited_once()
    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["event_type"] == LifeEventType.reflection
    assert call_kwargs["text"] == reflection
    assert result.response_text


@pytest.mark.asyncio
async def test_reflection_from_intent_data(skill, ctx):
    """Reflection text from intent_data takes priority."""
    msg = _msg("some trigger text")
    intent_data = {"reflection": "Продуктивный день"}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, intent_data)

    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["text"] == "Продуктивный день"


@pytest.mark.asyncio
async def test_silent_mode(skill, ctx):
    """Silent mode returns empty response."""
    msg = _msg("Сегодня было хорошо")
    p_save, p_mode = _patch_helpers(mode="silent")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert result.response_text == ""


@pytest.mark.asyncio
async def test_coaching_mode_calls_llm(skill, ctx):
    """Coaching mode calls generate_text and includes LLM response."""
    msg = _msg("Сегодня всё успел")
    p_save, p_mode = _patch_helpers(mode="coaching")

    with (
        p_save,
        p_mode,
        patch(
            "src.skills.day_reflection.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Отлично!</b> Вы продуктивно провели день.",
        ) as mock_llm,
    ):
        result = await skill.execute(msg, ctx, {})

    mock_llm.assert_awaited_once()
    assert "Отлично" in result.response_text


@pytest.mark.asyncio
async def test_coaching_mode_fallback_on_llm_error(skill, ctx):
    """Coaching mode falls back to template when LLM fails."""
    msg = _msg("Сегодня всё успел")
    p_save, p_mode = _patch_helpers(mode="coaching")

    with (
        p_save,
        p_mode,
        patch(
            "src.skills.day_reflection.handler.generate_text",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM unavailable"),
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "\U0001f4a1" in result.response_text
    assert "рефлексия" in result.response_text.lower()


@pytest.mark.asyncio
async def test_receipt_mode_does_not_call_llm(skill, ctx):
    """Receipt mode does NOT call generate_text."""
    msg = _msg("Устал но доволен")
    p_save, p_mode = _patch_helpers(mode="receipt")

    with (
        p_save,
        p_mode,
        patch(
            "src.skills.day_reflection.handler.generate_text",
            new_callable=AsyncMock,
        ) as mock_llm,
    ):
        await skill.execute(msg, ctx, {})

    mock_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_receipt_mode(skill, ctx):
    """Receipt mode returns formatted receipt without insight."""
    msg = _msg("Устал но доволен")
    p_save, p_mode = _patch_helpers(mode="receipt")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert result.response_text
    assert "\U0001f4a1" not in result.response_text
