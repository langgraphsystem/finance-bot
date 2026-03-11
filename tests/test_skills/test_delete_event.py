"""Tests for delete_event skill."""

import uuid
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.delete_event.handler import (
    DeleteEventSkill,
    execute_delete_event,
    skill,
)


def _make_context(**overrides):
    defaults = {
        "user_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "role": "owner",
        "language": "ru",
        "currency": "USD",
        "business_type": None,
        "categories": [],
        "merchant_mappings": [],
        "timezone": "America/Chicago",
    }
    defaults.update(overrides)
    return SessionContext(**defaults)


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="msg-1",
        user_id="tg_123",
        chat_id="chat_123",
        type=MessageType.text,
        text=text,
    )


SAMPLE_EVENTS = [
    {
        "id": "evt-1",
        "summary": "Поход в Чикаго",
        "start": {"dateTime": "2026-03-14T10:00:00-05:00"},
    },
    {
        "id": "evt-2",
        "summary": "Встреча с врачом",
        "start": {"dateTime": "2026-03-15T14:00:00-05:00"},
    },
]


def test_skill_metadata():
    assert skill.name == "delete_event"
    assert "delete_event" in skill.intents
    assert isinstance(skill, DeleteEventSkill)


async def test_delete_event_confirm_flow():
    """Skill lists events, LLM matches, shows confirmation buttons."""
    ctx = _make_context()
    msg = _make_message("удалить мероприятие из календаря Поход в Чикаго")

    mock_google = AsyncMock()
    mock_google.list_events.return_value = SAMPLE_EVENTS

    with (
        patch(
            "src.skills.delete_event.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.delete_event.handler.get_google_client",
            new_callable=AsyncMock,
            return_value=mock_google,
        ),
        patch(
            "src.skills.delete_event.handler._match_event",
            new_callable=AsyncMock,
            return_value='{"event_id": "evt-1", "event_name": "Поход в Чикаго"}',
        ),
        patch(
            "src.core.pending_actions.store_pending_action",
            new_callable=AsyncMock,
            return_value="pending-abc",
        ) as mock_store,
    ):
        result = await skill.execute(msg, ctx, {})

    assert "Поход в Чикаго" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action:pending-abc" in result.buttons[0]["callback"]
    mock_store.assert_called_once()
    stored = mock_store.call_args
    assert stored.kwargs["intent"] == "delete_event"


async def test_delete_event_no_events():
    ctx = _make_context()
    msg = _make_message("удали встречу")
    mock_google = AsyncMock()
    mock_google.list_events.return_value = []

    with (
        patch(
            "src.skills.delete_event.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.delete_event.handler.get_google_client",
            new_callable=AsyncMock,
            return_value=mock_google,
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "Нет предстоящих событий" in result.response_text


async def test_delete_event_no_match():
    ctx = _make_context()
    msg = _make_message("удали какое-то событие")
    mock_google = AsyncMock()
    mock_google.list_events.return_value = SAMPLE_EVENTS

    with (
        patch(
            "src.skills.delete_event.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.delete_event.handler.get_google_client",
            new_callable=AsyncMock,
            return_value=mock_google,
        ),
        patch(
            "src.skills.delete_event.handler._match_event",
            new_callable=AsyncMock,
            return_value='{"event_id": null, "event_name": null}',
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "Не удалось найти" in result.response_text
    assert "Поход в Чикаго" in result.response_text


async def test_execute_delete_event_success():
    """Callback executor deletes via Google Calendar API."""
    mock_google = AsyncMock()
    with patch(
        "src.skills.delete_event.handler.get_google_client",
        new_callable=AsyncMock,
        return_value=mock_google,
    ):
        result = await execute_delete_event(
            {"event_id": "evt-1", "event_name": "Поход в Чикаго", "language": "ru"},
            user_id="u-1",
        )

    assert "удалено" in result.lower()
    mock_google.delete_event.assert_called_once_with("evt-1")


async def test_execute_delete_event_error():
    mock_google = AsyncMock()
    mock_google.delete_event.side_effect = Exception("API error")
    with patch(
        "src.skills.delete_event.handler.get_google_client",
        new_callable=AsyncMock,
        return_value=mock_google,
    ):
        result = await execute_delete_event(
            {"event_id": "evt-1", "event_name": "Test", "language": "en"},
            user_id="u-1",
        )

    assert "Error" in result


async def test_i18n_english():
    ctx = _make_context(language="en")
    msg = _make_message("delete the meeting")
    mock_google = AsyncMock()
    mock_google.list_events.return_value = []

    with (
        patch(
            "src.skills.delete_event.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.delete_event.handler.get_google_client",
            new_callable=AsyncMock,
            return_value=mock_google,
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "No upcoming events" in result.response_text


async def test_i18n_spanish():
    ctx = _make_context(language="es")
    msg = _make_message("eliminar la reunión")
    mock_google = AsyncMock()
    mock_google.list_events.return_value = []

    with (
        patch(
            "src.skills.delete_event.handler.require_google_or_prompt",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.skills.delete_event.handler.get_google_client",
            new_callable=AsyncMock,
            return_value=mock_google,
        ),
    ):
        result = await skill.execute(msg, ctx, {})

    assert "No hay eventos" in result.response_text
