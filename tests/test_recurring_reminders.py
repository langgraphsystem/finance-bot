"""Tests for recurring reminder cron dispatcher — _compute_next_reminder."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from src.core.models.enums import ReminderRecurrence
from src.core.tasks.reminder_tasks import _compute_next_reminder


def _make_task(
    recurrence: ReminderRecurrence,
    reminder_at: datetime,
    original_time: str | None = None,
    recurrence_end_at: datetime | None = None,
) -> MagicMock:
    task = MagicMock()
    task.recurrence = recurrence
    task.reminder_at = reminder_at
    task.original_reminder_time = original_time
    task.recurrence_end_at = recurrence_end_at
    return task


# ---------------------------------------------------------------------------
# Daily recurrence
# ---------------------------------------------------------------------------


def test_daily_advances_by_one_day():
    task = _make_task(
        ReminderRecurrence.daily,
        datetime(2026, 3, 1, 5, 8, 0, tzinfo=UTC),
        "05:08",
    )
    next_at = _compute_next_reminder(task, datetime.now(UTC))
    assert next_at is not None
    assert next_at.day == 2
    assert next_at.month == 3
    assert next_at.hour == 5
    assert next_at.minute == 8


def test_daily_preserves_original_time():
    task = _make_task(
        ReminderRecurrence.daily,
        datetime(2026, 2, 19, 17, 28, 0, tzinfo=UTC),
        "17:28",
    )
    next_at = _compute_next_reminder(task, datetime.now(UTC))
    assert next_at.hour == 17
    assert next_at.minute == 28


def test_daily_crosses_month_boundary():
    task = _make_task(
        ReminderRecurrence.daily,
        datetime(2026, 2, 28, 8, 0, 0, tzinfo=UTC),
        "08:00",
    )
    next_at = _compute_next_reminder(task, datetime.now(UTC))
    assert next_at.month == 3
    assert next_at.day == 1


def test_daily_without_original_time():
    task = _make_task(
        ReminderRecurrence.daily,
        datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC),
        None,
    )
    next_at = _compute_next_reminder(task, datetime.now(UTC))
    assert next_at is not None
    assert next_at == task.reminder_at + timedelta(days=1)


# ---------------------------------------------------------------------------
# Weekly recurrence
# ---------------------------------------------------------------------------


def test_weekly_advances_by_seven_days():
    task = _make_task(
        ReminderRecurrence.weekly,
        datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC),
        "09:00",
    )
    next_at = _compute_next_reminder(task, datetime.now(UTC))
    assert next_at is not None
    assert next_at.day == 8
    assert next_at.hour == 9


# ---------------------------------------------------------------------------
# Monthly recurrence
# ---------------------------------------------------------------------------


def test_monthly_advances_to_next_month():
    task = _make_task(
        ReminderRecurrence.monthly,
        datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
        "10:00",
    )
    next_at = _compute_next_reminder(task, datetime.now(UTC))
    assert next_at is not None
    assert next_at.month == 2
    assert next_at.day == 15


def test_monthly_clamps_day_for_short_month():
    """January 31 → February 28 (non-leap year)."""
    task = _make_task(
        ReminderRecurrence.monthly,
        datetime(2026, 1, 31, 10, 0, 0, tzinfo=UTC),
        "10:00",
    )
    next_at = _compute_next_reminder(task, datetime.now(UTC))
    assert next_at is not None
    assert next_at.month == 2
    assert next_at.day == 28


def test_monthly_december_to_january():
    """December → January crosses year boundary."""
    task = _make_task(
        ReminderRecurrence.monthly,
        datetime(2026, 12, 15, 8, 0, 0, tzinfo=UTC),
        "08:00",
    )
    next_at = _compute_next_reminder(task, datetime.now(UTC))
    assert next_at is not None
    assert next_at.year == 2027
    assert next_at.month == 1
    assert next_at.day == 15


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_none_recurrence_returns_none():
    task = _make_task(
        ReminderRecurrence.none,
        datetime(2026, 3, 1, 8, 0, 0, tzinfo=UTC),
    )
    assert _compute_next_reminder(task, datetime.now(UTC)) is None
