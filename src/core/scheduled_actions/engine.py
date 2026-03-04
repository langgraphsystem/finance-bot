"""Runtime helpers for scheduled action execution."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.core.models.enums import ActionStatus, ScheduleKind
from src.core.models.scheduled_action import ScheduledAction


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


def _monthly_next(reference: datetime, day_of_month: int) -> datetime:
    year = reference.year + (reference.month // 12)
    month = (reference.month % 12) + 1
    safe_day = min(day_of_month, monthrange(year, month)[1])
    return reference.replace(year=year, month=month, day=safe_day)


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
    candidate = local_after.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if action.schedule_kind == ScheduleKind.daily:
        if candidate <= local_after:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)

    if action.schedule_kind == ScheduleKind.weekdays:
        if candidate <= local_after:
            candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)

    if action.schedule_kind == ScheduleKind.weekly:
        days = cfg.get("days") or [local_after.weekday()]
        try:
            target_weekday = int(days[0])
        except (TypeError, ValueError):
            target_weekday = local_after.weekday()
        delta_days = (target_weekday - local_after.weekday()) % 7
        candidate = local_after + timedelta(days=delta_days)
        candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_after:
            candidate += timedelta(days=7)
        return candidate.astimezone(UTC)

    if action.schedule_kind == ScheduleKind.monthly:
        raw_day = cfg.get("day_of_month")
        try:
            day_of_month = int(raw_day)
        except (TypeError, ValueError):
            day_of_month = local_after.day
        safe_day = min(day_of_month, monthrange(local_after.year, local_after.month)[1])
        candidate = local_after.replace(
            day=safe_day, hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= local_after:
            candidate = _monthly_next(candidate, day_of_month)
        return candidate.astimezone(UTC)

    # Fallback for unsupported schedule kinds (e.g. cron in P1+): daily.
    if candidate <= local_after:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def is_action_completed(action: ScheduledAction, now: datetime | None = None) -> bool:
    current = now or now_utc()
    if action.max_runs is not None and action.run_count >= action.max_runs:
        return True
    if action.end_at is not None and current >= action.end_at:
        return True
    return False


def complete_action(action: ScheduledAction) -> None:
    action.status = ActionStatus.completed
    action.next_run_at = None


def apply_success(action: ScheduledAction, run_started_at: datetime) -> None:
    action.failure_count = 0
    action.run_count += 1
    action.last_run_at = run_started_at
    action.last_success_at = now_utc()

    if is_action_completed(action, now_utc()):
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

