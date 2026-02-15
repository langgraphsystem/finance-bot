"""Tests for life_helpers functions."""

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.life_helpers import (
    _type_icon,
    format_receipt,
    format_timeline,
    get_communication_mode,
)
from src.core.models.enums import LifeEventType

VALID_UUID = str(uuid.uuid4())


def _make_event(
    text: str = "test",
    event_type: LifeEventType = LifeEventType.note,
    tags: list[str] | None = None,
    event_date: date | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock LifeEvent."""
    event = MagicMock()
    event.text = text
    event.type = event_type
    event.tags = tags
    event.date = event_date or date.today()
    event.created_at = created_at or datetime.now()
    return event


# --- get_communication_mode ---


@pytest.mark.asyncio
async def test_get_communication_mode_default():
    """Default communication mode is 'receipt'."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "src.core.life_helpers.async_session",
        return_value=mock_ctx,
    ):
        mode = await get_communication_mode(VALID_UUID)

    assert mode == "receipt"


@pytest.mark.asyncio
async def test_get_communication_mode_from_prefs():
    """Communication mode is read from user preferences."""
    prefs = {"communication_mode": "coaching"}
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = prefs

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "src.core.life_helpers.async_session",
        return_value=mock_ctx,
    ):
        mode = await get_communication_mode(VALID_UUID)

    assert mode == "coaching"


@pytest.mark.asyncio
async def test_get_communication_mode_on_error():
    """Returns default when an exception occurs."""
    with patch(
        "src.core.life_helpers.async_session",
        side_effect=RuntimeError("DB down"),
    ):
        mode = await get_communication_mode(VALID_UUID)

    assert mode == "receipt"


# --- format_receipt ---


def test_format_receipt_with_tags():
    """Receipt includes tags in brackets."""
    result = format_receipt(
        LifeEventType.note,
        "моя заметка",
        ["тег1", "тег2"],
    )

    assert "моя заметка" in result
    assert "[тег1, тег2]" in result
    assert "\U0001f4dd" in result  # note icon


def test_format_receipt_without_tags():
    """Receipt without tags has no brackets."""
    result = format_receipt(LifeEventType.drink, "coffee x1", None)

    assert "coffee x1" in result
    assert "[" not in result
    assert "\u2615" in result  # drink icon


def test_format_receipt_long_text_truncated():
    """Text longer than 80 chars is truncated."""
    long_text = "a" * 120
    result = format_receipt(LifeEventType.note, long_text, None)

    # 80 chars + icon prefix
    assert len(result) < 120


# --- format_timeline ---


def test_format_timeline_with_events():
    """Timeline formats events grouped by date."""
    now = datetime.now()
    events = [
        _make_event(
            "заметка",
            LifeEventType.note,
            tags=["тег"],
            event_date=date.today(),
            created_at=now,
        ),
        _make_event(
            "кофе",
            LifeEventType.drink,
            event_date=date.today(),
            created_at=now,
        ),
    ]

    result = format_timeline(events)

    assert date.today().strftime("%d.%m.%Y") in result
    assert "заметка" in result
    assert "кофе" in result
    assert "#тег" in result


def test_format_timeline_empty():
    """Empty events list returns 'nothing found' message."""
    result = format_timeline([])

    assert "Ничего не найдено" in result


def test_format_timeline_long_text_truncated():
    """Event text longer than 100 chars is truncated."""
    event = _make_event(
        "x" * 150,
        LifeEventType.note,
        event_date=date.today(),
        created_at=datetime.now(),
    )

    result = format_timeline([event])

    assert "..." in result


# --- _type_icon ---


def test_type_icon_note():
    """Note icon is memo emoji."""
    assert _type_icon(LifeEventType.note) == "\U0001f4dd"


def test_type_icon_food():
    """Food icon is plate emoji."""
    assert _type_icon(LifeEventType.food) == "\U0001f37d"


def test_type_icon_drink():
    """Drink icon is coffee emoji."""
    assert _type_icon(LifeEventType.drink) == "\u2615"


def test_type_icon_mood():
    """Mood icon is smiley emoji."""
    assert _type_icon(LifeEventType.mood) == "\U0001f60a"


def test_type_icon_task():
    """Task icon is check mark emoji."""
    assert _type_icon(LifeEventType.task) == "\u2705"


def test_type_icon_reflection():
    """Reflection icon is moon emoji."""
    assert _type_icon(LifeEventType.reflection) == "\U0001f319"
