"""Tests for quick_capture skill."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import LifeEventType
from src.gateway.types import IncomingMessage, MessageType
from src.skills.quick_capture.handler import QuickCaptureSkill


@pytest.fixture
def skill():
    return QuickCaptureSkill()


@pytest.fixture
def message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="идея: сделать лендинг",
    )


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


def _mock_event(event_id: str = "evt-1") -> MagicMock:
    """Create a mock LifeEvent with an id attribute."""
    event = MagicMock()
    event.id = event_id
    return event


@pytest.mark.asyncio
async def test_note_saved_with_auto_tags(skill, message, ctx):
    """Note is saved with auto-generated tags."""
    mock_event = _mock_event()

    with (
        patch(
            "src.skills.quick_capture.handler.save_life_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ) as mock_save,
        patch(
            "src.skills.quick_capture.handler.auto_tag",
            new_callable=AsyncMock,
            return_value=["лендинг", "идея"],
        ),
        patch(
            "src.skills.quick_capture.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value="receipt",
        ),
    ):
        result = await skill.execute(message, ctx, {})

    mock_save.assert_awaited_once()
    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["event_type"] == LifeEventType.note
    assert call_kwargs["tags"] == ["лендинг", "идея"]
    assert "лендинг" in call_kwargs["text"]
    assert result.response_text  # non-empty receipt


@pytest.mark.asyncio
async def test_empty_text_returns_prompt(skill, ctx):
    """Empty text returns a prompt asking for input."""
    msg = IncomingMessage(
        id="msg-2",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="",
    )

    result = await skill.execute(msg, ctx, {})

    assert "Что записать" in result.response_text


@pytest.mark.asyncio
async def test_silent_mode_returns_empty_response(skill, message, ctx):
    """Silent mode returns empty response text."""
    mock_event = _mock_event()

    with (
        patch(
            "src.skills.quick_capture.handler.save_life_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ),
        patch(
            "src.skills.quick_capture.handler.auto_tag",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.skills.quick_capture.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value="silent",
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert result.response_text == ""


@pytest.mark.asyncio
async def test_coaching_mode_includes_insight(skill, message, ctx):
    """Coaching mode includes an insight hint in the response."""
    mock_event = _mock_event()

    with (
        patch(
            "src.skills.quick_capture.handler.save_life_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ),
        patch(
            "src.skills.quick_capture.handler.auto_tag",
            new_callable=AsyncMock,
            return_value=["тег"],
        ),
        patch(
            "src.skills.quick_capture.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value="coaching",
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert "\U0001f4a1" in result.response_text
    assert "Заметка сохранена" in result.response_text


@pytest.mark.asyncio
async def test_mem0_storage_in_background_tasks(skill, message, ctx):
    """Mem0 storage function is added to background_tasks."""
    mock_event = _mock_event()

    with (
        patch(
            "src.skills.quick_capture.handler.save_life_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ),
        patch(
            "src.skills.quick_capture.handler.auto_tag",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "src.skills.quick_capture.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value="receipt",
        ),
    ):
        result = await skill.execute(message, ctx, {})

    assert len(result.background_tasks) == 1
    assert callable(result.background_tasks[0])


@pytest.mark.asyncio
async def test_note_from_intent_data(skill, ctx):
    """Note text is taken from intent_data['note'] when provided."""
    msg = IncomingMessage(
        id="msg-3",
        user_id="tg_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="quick capture command",
    )
    intent_data = {"note": "купить молоко"}
    mock_event = _mock_event()

    with (
        patch(
            "src.skills.quick_capture.handler.save_life_event",
            new_callable=AsyncMock,
            return_value=mock_event,
        ) as mock_save,
        patch(
            "src.skills.quick_capture.handler.auto_tag",
            new_callable=AsyncMock,
            return_value=["покупки"],
        ),
        patch(
            "src.skills.quick_capture.handler.get_communication_mode",
            new_callable=AsyncMock,
            return_value="receipt",
        ),
    ):
        result = await skill.execute(msg, ctx, intent_data)

    call_kwargs = mock_save.call_args.kwargs
    assert call_kwargs["text"] == "купить молоко"
    assert result.response_text
