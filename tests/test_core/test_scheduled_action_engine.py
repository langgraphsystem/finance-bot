"""Tests for scheduled action runtime engine helpers."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.core.models.enums import ActionStatus, ScheduleKind
from src.core.scheduled_actions.engine import (
    apply_failure,
    apply_success,
    backoff_minutes,
    compute_next_run,
)


def _action(**kwargs):
    base = {
        "action_kind": "digest",
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


@pytest.mark.parametrize(
    ("timezone", "expected_utc"),
    [
        ("America/New_York", datetime(2026, 3, 9, 12, 0, tzinfo=UTC)),
        ("Europe/Moscow", datetime(2026, 3, 9, 5, 0, tzinfo=UTC)),
    ],
)
def test_compute_next_run_weekdays_preserves_wall_clock_by_timezone(
    timezone: str,
    expected_utc: datetime,
):
    action = _action(
        schedule_kind=ScheduleKind.weekdays,
        schedule_config={"time": "08:00"},
        timezone=timezone,
    )
    # Friday, after local 08:00, should schedule Monday at local 08:00.
    after = datetime(2026, 3, 6, 14, 0, tzinfo=UTC)

    next_run = compute_next_run(action, after=after)

    assert next_run == expected_utc


def test_compute_next_run_daily_spring_forward_nonexistent_time():
    action = _action(
        schedule_kind=ScheduleKind.daily,
        schedule_config={"time": "02:30"},
        timezone="America/New_York",
    )
    # Day before DST jump, evening local time.
    after = datetime(2026, 3, 7, 23, 0, tzinfo=UTC)

    next_run = compute_next_run(action, after=after)

    # 02:30 local doesn't exist on 2026-03-08 in New York, so it shifts to 03:00 local.
    assert next_run == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)


def test_compute_next_run_daily_fall_back_keeps_first_occurrence_only():
    action = _action(
        schedule_kind=ScheduleKind.daily,
        schedule_config={"time": "01:30"},
        timezone="America/New_York",
    )
    # After fallback happened (01:00 EST), first 01:30 occurrence already passed.
    after = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)

    next_run = compute_next_run(action, after=after)

    assert next_run == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)


def test_compute_next_run_cron_valid_expression():
    action = _action(
        schedule_kind=ScheduleKind.cron,
        schedule_config={"cron_expr": "*/10 * * * *"},
        timezone="UTC",
    )
    after = datetime(2026, 3, 4, 8, 3, tzinfo=UTC)

    next_run = compute_next_run(action, after=after)

    assert next_run == datetime(2026, 3, 4, 8, 10, tzinfo=UTC)


def test_compute_next_run_cron_too_frequent_returns_none():
    action = _action(
        schedule_kind=ScheduleKind.cron,
        schedule_config={"cron_expr": "* * * * *"},
        timezone="UTC",
    )
    after = datetime(2026, 3, 4, 8, 3, tzinfo=UTC)

    next_run = compute_next_run(action, after=after)

    assert next_run is None


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


def test_apply_success_completes_when_max_runs_reached():
    action = _action(run_count=0, max_runs=1, schedule_kind=ScheduleKind.daily)
    run_started_at = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

    apply_success(action, run_started_at)

    assert action.run_count == 1
    assert action.status == ActionStatus.completed
    assert action.next_run_at is None


def test_apply_success_completes_when_end_at_passed():
    action = _action(
        run_count=0,
        max_runs=None,
        end_at=datetime(2020, 1, 1, 0, 0, tzinfo=UTC),
        schedule_kind=ScheduleKind.daily,
    )
    run_started_at = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

    apply_success(action, run_started_at)

    assert action.status == ActionStatus.completed
    assert action.next_run_at is None


def test_apply_success_outcome_task_completed_when_tasks_empty():
    action = _action(
        action_kind="outcome",
        schedule_kind=ScheduleKind.daily,
        schedule_config={"time": "08:00", "completion_condition": "task_completed"},
        sources=["tasks"],
    )
    run_started_at = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

    apply_success(action, run_started_at, payload={"tasks": ""})

    assert action.status == ActionStatus.completed
    assert action.next_run_at is None


def test_apply_success_outcome_invoice_paid_when_outstanding_empty():
    action = _action(
        action_kind="outcome",
        schedule_kind=ScheduleKind.daily,
        schedule_config={"time": "08:00", "completion_condition": "invoice_paid"},
        sources=["outstanding"],
    )
    run_started_at = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

    apply_success(action, run_started_at, payload={"outstanding": ""})

    assert action.status == ActionStatus.completed
    assert action.next_run_at is None


def test_apply_success_outcome_does_not_complete_when_open_items_present():
    action = _action(
        action_kind="outcome",
        schedule_kind=ScheduleKind.daily,
        schedule_config={"time": "08:00", "completion_condition": "task_completed"},
        sources=["tasks"],
    )
    run_started_at = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)

    apply_success(action, run_started_at, payload={"tasks": "Open tasks (1):\n- Pay bill"})

    assert action.status == ActionStatus.active
    assert action.next_run_at == datetime(2026, 3, 5, 8, 0, tzinfo=UTC)
