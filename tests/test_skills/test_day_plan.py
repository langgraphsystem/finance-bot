"""Tests for day_plan skill."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import LifeEventType
from src.gateway.types import IncomingMessage, MessageType
from src.skills.day_plan.handler import DayPlanSkill


@pytest.fixture
def skill():
    return DayPlanSkill()


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
            "src.skills.day_plan.handler.save_life_event",
            new_callable=AsyncMock,
        ),
        patch(
            "src.skills.day_plan.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value=mode,
        ),
    )


@pytest.mark.asyncio
async def test_tasks_parsed_from_comma_separated(skill, ctx):
    """Comma-separated tasks are parsed correctly."""
    msg = _msg("код, тесты, деплой")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert mock_save.call_count == 3
    assert "код" in result.response_text
    assert "тесты" in result.response_text
    assert "деплой" in result.response_text


@pytest.mark.asyncio
async def test_tasks_parsed_from_newline_separated(skill, ctx):
    """Newline-separated tasks are parsed correctly."""
    msg = _msg("написать тесты\nсделать ревью\nобновить доку")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert mock_save.call_count == 3
    assert "тесты" in result.response_text
    assert "ревью" in result.response_text
    assert "доку" in result.response_text


@pytest.mark.asyncio
async def test_numbered_list_cleanup(skill, ctx):
    """Numbered prefixes like '1.' or '2)' are stripped."""
    msg = _msg("1. код\n2. тесты\n3. деплой")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    assert mock_save.call_count == 3
    # Verify the numbering was stripped
    calls = mock_save.call_args_list
    assert calls[0].kwargs["text"] == "код"
    assert calls[1].kwargs["text"] == "тесты"
    assert calls[2].kwargs["text"] == "деплой"


@pytest.mark.asyncio
async def test_first_task_gets_top1_priority(skill, ctx):
    """First task gets 'top1' priority, rest get 'normal'."""
    msg = _msg("главное, второстепенное")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    calls = mock_save.call_args_list
    assert calls[0].kwargs["data"]["priority"] == "top1"
    assert calls[1].kwargs["data"]["priority"] == "normal"
    # Check fire emoji for top1
    assert "\U0001f525" in result.response_text


@pytest.mark.asyncio
async def test_empty_input_returns_prompt(skill, ctx):
    """Empty input returns a prompt asking for tasks."""
    msg = _msg("")

    result = await skill.execute(msg, ctx, {})

    assert "Какие задачи" in result.response_text


@pytest.mark.asyncio
async def test_tasks_from_intent_data(skill, ctx):
    """Tasks provided via intent_data are used directly."""
    msg = _msg("план на день")
    intent_data = {"tasks": ["рефакторинг", "код ревью"]}
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, intent_data)

    assert mock_save.call_count == 2
    calls = mock_save.call_args_list
    assert calls[0].kwargs["text"] == "рефакторинг"
    assert calls[1].kwargs["text"] == "код ревью"


@pytest.mark.asyncio
async def test_event_type_is_task(skill, ctx):
    """All saved events have LifeEventType.task."""
    msg = _msg("задача")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["event_type"] == LifeEventType.task


@pytest.mark.asyncio
async def test_order_field_increments(skill, ctx):
    """Order field increments for each task."""
    msg = _msg("a, b, c")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    calls = mock_save.call_args_list
    assert calls[0].kwargs["data"]["order"] == 1
    assert calls[1].kwargs["data"]["order"] == 2
    assert calls[2].kwargs["data"]["order"] == 3


@pytest.mark.asyncio
async def test_silent_mode(skill, ctx):
    """Silent mode returns empty response."""
    msg = _msg("задача")
    p_save, p_mode = _patch_helpers(mode="silent")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert result.response_text == ""


@pytest.mark.asyncio
async def test_coaching_mode_includes_tip(skill, ctx):
    """Coaching mode includes a focus tip."""
    msg = _msg("задача1, задача2")
    p_save, p_mode = _patch_helpers(mode="coaching")

    with p_save, p_mode:
        result = await skill.execute(msg, ctx, {})

    assert "\U0001f4a1" in result.response_text
    assert "Фокус" in result.response_text


@pytest.mark.asyncio
async def test_done_field_defaults_false(skill, ctx):
    """All tasks have done=False by default."""
    msg = _msg("тест")
    p_save, p_mode = _patch_helpers()

    with p_save as mock_save, p_mode:
        await skill.execute(msg, ctx, {})

    data = mock_save.call_args.kwargs["data"]
    assert data["done"] is False
