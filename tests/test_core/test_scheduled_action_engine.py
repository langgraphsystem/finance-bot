"""Tests for scheduled action runtime engine helpers."""

from datetime import UTC, datetime
from types import SimpleNamespace

from src.core.models.enums import ActionStatus, ScheduleKind
from src.core.scheduled_actions.engine import (
    apply_failure,
    backoff_minutes,
    compute_next_run,
)


def _action(**kwargs):
    base = {
        "schedule_kind": ScheduleKind.daily,
        "schedule_config": {"time": "08:00"},
        "timezone": "UTC",
        "next_run_at": datetime(2026, 3, 4, 8, 0, tzinfo=UTC),
        "run_count": 0,
        "max_runs": None,
        "end_at": None,
        "status": ActionStatus.active,
        "failure_count": 0,
        "max_failures": 3,
        "last_run_at": None,
        "last_success_at": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_compute_next_run_daily():
    action = _action()
    after = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)

    next_run = compute_next_run(action, after=after)

    assert next_run == datetime(2026, 3, 5, 8, 0, tzinfo=UTC)


def test_compute_next_run_once_past_returns_none():
    action = _action(
        schedule_kind=ScheduleKind.once,
        schedule_config={"run_at": "2026-03-03T10:00:00+00:00"},
    )
    after = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)

    next_run = compute_next_run(action, after=after)

    assert next_run is None


def test_compute_next_run_weekdays_skips_weekend():
    action = _action(schedule_kind=ScheduleKind.weekdays, schedule_config={"time": "08:00"})
    # Friday evening.
    after = datetime(2026, 3, 6, 22, 0, tzinfo=UTC)

    next_run = compute_next_run(action, after=after)

    # Monday 2026-03-09 08:00 UTC.
    assert next_run == datetime(2026, 3, 9, 8, 0, tzinfo=UTC)


def test_backoff_policy():
    assert backoff_minutes(1) == 1
    assert backoff_minutes(2) == 5
    assert backoff_minutes(3) == 15
    assert backoff_minutes(10) == 15


def test_apply_failure_pauses_after_max_failures():
    action = _action(failure_count=2, max_failures=3)
    now = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

    apply_failure(action, now)

    assert action.failure_count == 3
    assert action.status == ActionStatus.paused
