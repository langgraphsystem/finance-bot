"""Runtime helpers for scheduled action execution."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from croniter import CroniterBadCronError, CroniterBadDateError, croniter

from src.core.models.enums import ActionStatus, ScheduleKind
from src.core.models.scheduled_action import ScheduledAction

_EMPTY_CONDITIONS = {"empty", "until_empty", "all_clear"}
_TASK_CONDITIONS = {"task_completed", "tasks_completed", "tasks_empty"}
_INVOICE_CONDITIONS = {"invoice_paid", "outstanding_cleared", "outstanding_empty"}


def now_utc() -> datetime:
    return datetime.now(UTC)


def _safe_timezone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _extract_hhmm(action: ScheduledAction, local_now: datetime) -> tuple[int, int]:
    raw_time = (action.schedule_config or {}).get("time")
    if isinstance(raw_time, str) and ":" in raw_time:
        try:
            hh, mm = raw_time.split(":", maxsplit=1)
            return int(hh), int(mm)
        except ValueError:
            pass

    if action.next_run_at:
        local_next = action.next_run_at.astimezone(local_now.tzinfo)
        return local_next.hour, local_next.minute

    return 9, 0


def _monthly_next(reference: date, day_of_month: int) -> date:
    year = reference.year + (reference.month // 12)
    month = (reference.month % 12) + 1
    safe_day = min(day_of_month, monthrange(year, month)[1])
    return date(year, month, safe_day)


def _is_valid_local_dt(candidate: datetime) -> bool:
    """Return True when local datetime exists in timezone (not in DST gap)."""
    roundtrip = candidate.astimezone(UTC).astimezone(candidate.tzinfo)
    return (
        roundtrip.year == candidate.year
        and roundtrip.month == candidate.month
        and roundtrip.day == candidate.day
        and roundtrip.hour == candidate.hour
        and roundtrip.minute == candidate.minute
    )


def _resolve_local_dt(tz: ZoneInfo, run_date: date, hour: int, minute: int) -> datetime:
    """Resolve a wall-clock time in timezone with DST-safe behavior.

    - For ambiguous local time (fall-back), selects the first occurrence (fold=0).
    - For non-existent local time (spring-forward), shifts to first valid minute after gap.
    """
    candidate = datetime(
        run_date.year,
        run_date.month,
        run_date.day,
        hour,
        minute,
        tzinfo=tz,
        fold=0,
    )
    if _is_valid_local_dt(candidate):
        return candidate

    probe = datetime(run_date.year, run_date.month, run_date.day, hour, minute)
    for offset in range(1, 24 * 60 + 1):
        shifted = probe + timedelta(minutes=offset)
        shifted_local = datetime(
            shifted.year,
            shifted.month,
            shifted.day,
            shifted.hour,
            shifted.minute,
            tzinfo=tz,
            fold=0,
        )
        if _is_valid_local_dt(shifted_local):
            return shifted_local
    return candidate


def _is_not_future(candidate: datetime, local_after: datetime) -> bool:
    """Compare datetimes by absolute instant to handle DST folds correctly."""
    return candidate.astimezone(UTC) <= local_after.astimezone(UTC)


def _cron_next(expr: str, base_local: datetime, tz: ZoneInfo) -> datetime:
    itr = croniter(expr, base_local)
    next_dt = itr.get_next(datetime)
    if next_dt.tzinfo is None:
        next_dt = next_dt.replace(tzinfo=tz)
    return next_dt.astimezone(tz)


def is_valid_cron_expression(expr: str, *, min_interval_minutes: int = 5) -> bool:
    """Validate cron expression and enforce minimum interval."""
    if not expr or not isinstance(expr, str):
        return False
    try:
        base = datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC"))
        first = _cron_next(expr, base, ZoneInfo("UTC"))
        second = _cron_next(expr, first, ZoneInfo("UTC"))
    except (CroniterBadCronError, CroniterBadDateError, ValueError):
        return False
    return (second - first) >= timedelta(minutes=min_interval_minutes)


def compute_next_run(action: ScheduledAction, after: datetime | None = None) -> datetime | None:
    """Compute next run in UTC according to action schedule."""
    after_utc = after or now_utc()
    tz = _safe_timezone(action.timezone)
    local_after = after_utc.astimezone(tz)
    cfg = action.schedule_config or {}

    if action.schedule_kind == ScheduleKind.once:
        run_at = cfg.get("run_at")
        if isinstance(run_at, str):
            try:
                parsed = datetime.fromisoformat(run_at)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=tz)
                parsed_utc = parsed.astimezone(UTC)
                return parsed_utc if parsed_utc > after_utc else None
            except ValueError:
                return None
        if action.next_run_at and action.next_run_at > after_utc:
            return action.next_run_at
        return None

    hour, minute = _extract_hhmm(action, local_after)
    if action.schedule_kind == ScheduleKind.daily:
        target_date = local_after.date()
        candidate = _resolve_local_dt(tz, target_date, hour, minute)
        if _is_not_future(candidate, local_after):
            candidate = _resolve_local_dt(tz, target_date + timedelta(days=1), hour, minute)
        return candidate.astimezone(UTC)

    if action.schedule_kind == ScheduleKind.weekdays:
        target_date = local_after.date()
        while True:
            if target_date.weekday() >= 5:
                target_date += timedelta(days=1)
                continue
            candidate = _resolve_local_dt(tz, target_date, hour, minute)
            if _is_not_future(candidate, local_after):
                target_date += timedelta(days=1)
                continue
            break
        return candidate.astimezone(UTC)

    if action.schedule_kind == ScheduleKind.weekly:
        days = cfg.get("days") or [local_after.weekday()]
        try:
            target_weekday = int(days[0])
        except (TypeError, ValueError):
            target_weekday = local_after.weekday()
        delta_days = (target_weekday - local_after.weekday()) % 7
        target_date = local_after.date() + timedelta(days=delta_days)
        candidate = _resolve_local_dt(tz, target_date, hour, minute)
        if _is_not_future(candidate, local_after):
            candidate = _resolve_local_dt(tz, target_date + timedelta(days=7), hour, minute)
        return candidate.astimezone(UTC)

    if action.schedule_kind == ScheduleKind.monthly:
        raw_day = cfg.get("day_of_month")
        try:
            day_of_month = int(raw_day)
        except (TypeError, ValueError):
            day_of_month = local_after.day
        safe_day = min(day_of_month, monthrange(local_after.year, local_after.month)[1])
        target_date = date(local_after.year, local_after.month, safe_day)
        candidate = _resolve_local_dt(tz, target_date, hour, minute)
        if _is_not_future(candidate, local_after):
            next_month_date = _monthly_next(target_date, day_of_month)
            candidate = _resolve_local_dt(tz, next_month_date, hour, minute)
        return candidate.astimezone(UTC)

    if action.schedule_kind == ScheduleKind.cron:
        cron_expr = cfg.get("cron_expr")
        if not isinstance(cron_expr, str) or not is_valid_cron_expression(cron_expr):
            return None
        try:
            candidate = _cron_next(cron_expr, local_after, tz)
            while (candidate.astimezone(UTC) - local_after.astimezone(UTC)) < timedelta(minutes=5):
                candidate = _cron_next(cron_expr, candidate, tz)
        except (CroniterBadCronError, CroniterBadDateError, ValueError):
            return None
        return candidate.astimezone(UTC)

    # Fallback for unsupported schedule kinds (e.g. cron in P1+): daily.
    candidate = _resolve_local_dt(tz, local_after.date(), hour, minute)
    if _is_not_future(candidate, local_after):
        candidate = _resolve_local_dt(tz, local_after.date() + timedelta(days=1), hour, minute)
    return candidate.astimezone(UTC)


def _payload_value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_payload_value_to_text(v) for v in value.values())
    if isinstance(value, list | tuple | set):
        return " ".join(_payload_value_to_text(item) for item in value)
    return str(value)


def _is_empty_payload_value(value: Any) -> bool:
    return not _payload_value_to_text(value).strip()


def _normalized_completion_condition(raw: Any) -> str:
    condition = str(raw or "empty").strip().lower()
    if condition in _TASK_CONDITIONS:
        return "task_completed"
    if condition in _INVOICE_CONDITIONS:
        return "invoice_paid"
    return "empty"


def is_action_completed(
    action: ScheduledAction,
    now: datetime | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Check if action should be marked as completed."""
    current = now or now_utc()
    if action.max_runs is not None and action.run_count >= action.max_runs:
        return True
    if action.end_at is not None and current >= action.end_at:
        return True

    if getattr(action, "action_kind", "digest") == "outcome" and payload is not None:
        cfg = action.schedule_config or {}
        condition = _normalized_completion_condition(cfg.get("completion_condition", "empty"))
        if condition == "task_completed":
            return "tasks" in payload and _is_empty_payload_value(payload.get("tasks"))
        if condition == "invoice_paid":
            return "outstanding" in payload and _is_empty_payload_value(payload.get("outstanding"))
        if condition == "empty":
            # Completed if all collected sources are empty
            return all(_is_empty_payload_value(text) for text in payload.values())

    return False


def complete_action(action: ScheduledAction) -> None:
    action.status = ActionStatus.completed
    action.next_run_at = None


def apply_success(
    action: ScheduledAction,
    run_started_at: datetime,
    payload: dict[str, Any] | None = None,
) -> None:
    action.failure_count = 0
    action.run_count += 1
    action.last_run_at = run_started_at
    action.last_success_at = now_utc()

    if is_action_completed(action, now_utc(), payload=payload):
        complete_action(action)
        return

    next_run = compute_next_run(action, after=run_started_at)
    if next_run is None:
        complete_action(action)
        return

    action.next_run_at = next_run


def backoff_minutes(failure_count: int) -> int:
    if failure_count <= 1:
        return 1
    if failure_count == 2:
        return 5
    return 15


def apply_failure(action: ScheduledAction, run_started_at: datetime) -> None:
    action.failure_count += 1
    action.last_run_at = run_started_at
    if action.failure_count >= action.max_failures:
        action.status = ActionStatus.paused
        return

    action.next_run_at = now_utc() + timedelta(minutes=backoff_minutes(action.failure_count))
