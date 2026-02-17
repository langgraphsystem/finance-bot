"""Tests for life_helpers functions."""

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.life_helpers import (
    _format_event_text,
    _type_icon,
    format_receipt,
    format_save_response,
    format_timeline,
    get_communication_mode,
    resolve_life_period,
)
from src.core.models.enums import LifeEventType

VALID_UUID = str(uuid.uuid4())


def _make_event(
    text: str = "test",
    event_type: LifeEventType = LifeEventType.note,
    tags: list[str] | None = None,
    data: dict | None = None,
    event_date: date | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock LifeEvent."""
    event = MagicMock()
    event.text = text
    event.type = event_type
    event.tags = tags
    event.data = data
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


# --- resolve_life_period ---


def test_resolve_life_period_today():
    """Period 'today' returns today's date for both from and to."""
    today = date.today()
    d_from, d_to, label = resolve_life_period({"period": "today"})
    assert d_from == today
    assert d_to == today
    assert "сегодня" in label


def test_resolve_life_period_week():
    """Period 'week' returns Monday..today."""
    today = date.today()
    d_from, d_to, label = resolve_life_period({"period": "week"})
    assert d_from.weekday() == 0  # Monday
    assert d_to == today
    assert "неделю" in label


def test_resolve_life_period_month():
    """Period 'month' returns 1st of month..today."""
    today = date.today()
    d_from, d_to, label = resolve_life_period({"period": "month"})
    assert d_from == today.replace(day=1)
    assert d_to == today
    assert "месяц" in label


def test_resolve_life_period_prev_month():
    """Period 'prev_month' returns correct range."""
    d_from, d_to, label = resolve_life_period({"period": "prev_month"})
    assert d_from.day == 1
    assert d_to.month == d_from.month  # same month
    assert "прошлый" in label


def test_resolve_life_period_year():
    """Period 'year' returns Jan 1..today."""
    today = date.today()
    d_from, d_to, label = resolve_life_period({"period": "year"})
    assert d_from == date(today.year, 1, 1)
    assert d_to == today
    assert "год" in label


def test_resolve_life_period_day_with_date():
    """Period 'day' with explicit date returns that date."""
    d_from, d_to, label = resolve_life_period({"period": "day", "date": "2026-02-10"})
    assert d_from == date(2026, 2, 10)
    assert d_to == date(2026, 2, 10)
    assert "10.02.2026" in label


def test_resolve_life_period_custom_range():
    """Period 'custom' with both dates returns the range."""
    d_from, d_to, label = resolve_life_period({
        "period": "custom",
        "date_from": "2026-02-01",
        "date_to": "2026-02-10",
    })
    assert d_from == date(2026, 2, 1)
    assert d_to == date(2026, 2, 10)
    assert "01.02" in label
    assert "10.02.2026" in label


def test_resolve_life_period_custom_only_from():
    """Period 'custom' with only date_from falls back to today for date_to."""
    today = date.today()
    d_from, d_to, label = resolve_life_period({
        "period": "custom",
        "date_from": "2026-01-15",
    })
    assert d_from == date(2026, 1, 15)
    assert d_to == today


def test_resolve_life_period_none():
    """No period returns None, None, empty label."""
    d_from, d_to, label = resolve_life_period({})
    assert d_from is None
    assert d_to is None
    assert label == ""


def test_resolve_life_period_prev_week():
    """Period 'prev_week' returns 7 days ending before this Monday."""
    d_from, d_to, label = resolve_life_period({"period": "prev_week"})
    assert d_from.weekday() == 0  # Monday
    assert d_to.weekday() == 6  # Sunday
    assert (d_to - d_from).days == 6
    assert "прошлую" in label


# --- _format_event_text ---


def test_format_event_text_mood():
    """Mood event renders metrics inline."""
    event = _make_event(
        "mood summary",
        LifeEventType.mood,
        data={"mood": 8, "energy": 6, "stress": 3, "sleep_hours": 7.5},
    )
    result = _format_event_text(event)
    assert "\U0001f60a8" in result
    assert "\u26a16" in result
    assert "7.5h" in result


def test_format_event_text_task_done():
    """Done task shows check mark."""
    event = _make_event("buy milk", LifeEventType.task, data={"done": True})
    result = _format_event_text(event)
    assert "\u2705" in result
    assert "buy milk" in result


def test_format_event_text_task_undone():
    """Undone task shows empty square."""
    event = _make_event("buy milk", LifeEventType.task, data={"done": False})
    result = _format_event_text(event)
    assert "\u2b1c" in result


def test_format_event_text_drink():
    """Drink event shows item, count, and volume."""
    event = _make_event(
        "coffee x2",
        LifeEventType.drink,
        data={"item": "coffee", "count": 2, "volume_ml": 250},
    )
    result = _format_event_text(event)
    assert "coffee" in result
    assert "x2" in result
    assert "500ml" in result


def test_format_event_text_food():
    """Food event shows meal type and food item."""
    event = _make_event(
        "breakfast: oatmeal",
        LifeEventType.food,
        data={"meal_type": "breakfast", "food_item": "oatmeal"},
    )
    result = _format_event_text(event)
    assert "<i>breakfast</i>" in result
    assert "oatmeal" in result


def test_format_event_text_long_note_truncated():
    """Long note text is truncated at 100 chars."""
    event = _make_event("x" * 150, LifeEventType.note)
    result = _format_event_text(event)
    assert result.endswith("...")
    assert len(result) == 103  # 100 chars + "..."


# --- format_timeline truncation ---


def test_format_timeline_truncation():
    """Timeline shows truncation hint when events exceed max."""
    now = datetime.now()
    events = [
        _make_event(f"event {i}", event_date=date.today(), created_at=now)
        for i in range(25)
    ]
    result = format_timeline(events, max_events=10)
    assert "ещё 15 записей" in result


def test_format_timeline_no_truncation_when_under_limit():
    """No truncation hint when events are under max."""
    now = datetime.now()
    events = [_make_event(f"event {i}", created_at=now) for i in range(5)]
    result = format_timeline(events, max_events=20)
    assert "ещё" not in result


def test_format_timeline_tags_rendered():
    """Tags are rendered as italic hashtags in timeline."""
    event = _make_event("idea", tags=["finbot", "idea"], created_at=datetime.now())
    result = format_timeline([event])
    assert "<i>#finbot</i>" in result
    assert "<i>#idea</i>" in result


# --- format_save_response ---


def test_format_save_response_mood():
    """Mood response has visual scale bars."""
    result = format_save_response(
        LifeEventType.mood,
        "mood summary",
        data={"mood": 7, "energy": 5, "stress": 3},
    )
    assert "<b>Чек-ин</b>" in result
    assert "Настроение" in result
    assert "\u2588" in result  # filled bar
    assert "\u2591" in result  # empty bar
    assert "7/10" in result


def test_format_save_response_mood_with_sleep():
    """Mood response includes sleep hours."""
    result = format_save_response(
        LifeEventType.mood,
        "mood",
        data={"mood": 6, "sleep_hours": 7.5},
    )
    assert "7.5ч" in result
    assert "\U0001f634" in result  # sleep emoji


def test_format_save_response_drink():
    """Drink response shows item and volume."""
    result = format_save_response(
        LifeEventType.drink,
        "coffee",
        data={"item": "coffee", "count": 2, "volume_ml": 250},
    )
    assert "<b>Напиток</b>" in result
    assert "coffee" in result
    assert "x2" in result
    assert "500ml" in result


def test_format_save_response_food():
    """Food response shows meal type and item."""
    result = format_save_response(
        LifeEventType.food,
        "oatmeal",
        data={"meal_type": "breakfast", "food_item": "oatmeal"},
    )
    assert "<b>Питание</b>" in result
    assert "<i>breakfast</i>" in result
    assert "oatmeal" in result


def test_format_save_response_note_with_tags():
    """Note response includes tags as italic hashtags."""
    result = format_save_response(
        LifeEventType.note,
        "сделать лендинг",
        tags=["finbot", "идея"],
    )
    assert "<b>Заметка</b>" in result
    assert "сделать лендинг" in result
    assert "<i>#finbot</i>" in result
    assert "<i>#идея</i>" in result


def test_format_save_response_reflection():
    """Reflection response shows text."""
    result = format_save_response(
        LifeEventType.reflection,
        "Сегодня был продуктивный день",
    )
    assert "<b>Рефлексия</b>" in result
    assert "продуктивный день" in result


def test_format_save_response_long_text_truncated():
    """Long text in generic response is truncated."""
    long_text = "a" * 150
    result = format_save_response(LifeEventType.note, long_text)
    assert "..." in result
