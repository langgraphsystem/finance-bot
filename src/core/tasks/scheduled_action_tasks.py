"""Scheduled actions dispatcher cron task."""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.core.config import settings
from src.core.db import async_session
from src.core.life_helpers import get_communication_mode
from src.core.models.enums import ActionStatus, RunStatus
from src.core.models.scheduled_action import ScheduledAction
from src.core.models.scheduled_action_run import ScheduledActionRun
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.scheduled_actions.collectors import collect_sources
from src.core.scheduled_actions.engine import (
    apply_failure,
    apply_success,
    complete_action,
    is_action_completed,
    now_utc,
)
from src.core.scheduled_actions.formatter import format_action_message
from src.core.scheduled_actions.message_builder import build_action_buttons, send_action_message
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)

DISPATCH_BATCH_LIMIT = 50


def _in_active_hours(timezone: str, start_hour: int, end_hour: int) -> bool:
    try:
        from zoneinfo import ZoneInfo

        now_local = now_utc().astimezone(ZoneInfo(timezone))
    except Exception:
        now_local = now_utc()

    hour = now_local.hour
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    # Overnight window, e.g. 22..6
    return hour >= start_hour or hour < end_hour


def _run_duration_ms(run: ScheduledActionRun) -> int:
    if run.finished_at is None or run.started_at is None:
        return 0
    return int((run.finished_at - run.started_at).total_seconds() * 1000)


def _has_failed_sources(sources_status: dict[str, dict[str, object]]) -> bool:
    return any(meta.get("status") == "failed" for meta in sources_status.values())


@broker.task(schedule=[{"cron": "* * * * *"}])
async def dispatch_scheduled_actions() -> None:
    """Fetch due scheduled actions and execute them."""
    if not settings.ff_scheduled_actions:
        return

    now = now_utc()
    async with async_session() as session:
        result = await session.execute(
            select(ScheduledAction)
            .where(
                ScheduledAction.status == ActionStatus.active,
                ScheduledAction.next_run_at <= now,
            )
            .with_for_update(skip_locked=True)
            .limit(DISPATCH_BATCH_LIMIT)
        )
        due_actions = list(result.scalars().all())
        if not due_actions:
            return

        logger.info("SIA dispatcher: %d due actions found", len(due_actions))
        for action in due_actions:
            try:
                await _execute_action(session, action, now)
            except Exception:
                logger.exception("SIA dispatch failed for action %s", action.id)
                apply_failure(action, now)
        await session.commit()


async def _execute_action(session, action: ScheduledAction, now: datetime) -> None:  # noqa: ANN001
    if is_action_completed(action, now):
        complete_action(action)
        return

    run = ScheduledActionRun(
        scheduled_action_id=action.id,
        planned_run_at=action.next_run_at,
        started_at=now,
        status=RunStatus.running,
    )
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError:
        logger.info("SIA run already exists for action %s at %s", action.id, action.next_run_at)
        return

    telegram_id = await session.scalar(select(User.telegram_id).where(User.id == action.user_id))
    if telegram_id is None:
        run.status = RunStatus.failed
        run.error_code = "no_telegram_id"
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        apply_failure(action, now)
        return

    comm_mode = await get_communication_mode(str(action.user_id))
    if comm_mode == "silent":
        run.status = RunStatus.skipped
        run.error_code = "comm_mode_silent"
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        apply_success(action, now)
        return

    profile_row = await session.execute(
        select(
            UserProfile.active_hours_start,
            UserProfile.active_hours_end,
        ).where(UserProfile.user_id == action.user_id)
    )
    profile = profile_row.one_or_none()
    if profile is not None and not _in_active_hours(action.timezone, profile[0], profile[1]):
        run.status = RunStatus.skipped
        run.error_code = "outside_active_hours"
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        apply_success(action, now)
        return

    payload, sources_status = await collect_sources(action)
    message_text, model_used = format_action_message(
        action,
        payload,
        sources_status=sources_status,
        allow_synthesis=settings.ff_sia_synthesis,
    )
    buttons = build_action_buttons(action)

    try:
        await send_action_message(telegram_id, message_text, buttons=buttons)
    except Exception as exc:
        run.status = RunStatus.failed
        run.error_code = "send_failed"
        run.error_text = str(exc)[:500]
        run.sources_status = sources_status
        run.payload_snapshot = payload
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        apply_failure(action, now)
        return

    run.status = RunStatus.partial if _has_failed_sources(sources_status) else RunStatus.success
    run.sources_status = sources_status
    run.payload_snapshot = payload
    run.message_preview = message_text[:500]
    run.model_used = model_used
    run.finished_at = now_utc()
    run.duration_ms = _run_duration_ms(run)
    apply_success(action, now)
