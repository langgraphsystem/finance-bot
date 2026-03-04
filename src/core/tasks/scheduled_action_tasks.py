"""Scheduled actions dispatcher cron task."""

import logging
from datetime import datetime, timedelta

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
from src.core.scheduled_actions.i18n import t
from src.core.scheduled_actions.visuals import generate_budget_card
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


def _log_action_triggered(action: ScheduledAction) -> None:
    logger.info(
        "scheduled_action_triggered action_id=%s user_id=%s family_id=%s schedule_kind=%s "
        "output_mode=%s language=%s timezone=%s planned_run_at=%s",
        action.id,
        action.user_id,
        action.family_id,
        action.schedule_kind,
        action.output_mode,
        action.language,
        action.timezone,
        action.next_run_at,
    )


def _log_run_event(
    event_name: str,
    action: ScheduledAction,
    run: ScheduledActionRun,
    *,
    fallback_used: bool = False,
) -> None:
    sources_status = run.sources_status or {}
    failed_sources = sum(1 for meta in sources_status.values() if meta.get("status") == "failed")
    logger.info(
        "%s action_id=%s user_id=%s family_id=%s status=%s schedule_kind=%s output_mode=%s "
        "language=%s timezone=%s model_used=%s fallback_used=%s tokens_used=%s duration_ms=%s "
        "error_code=%s failed_sources=%s source_count=%s",
        event_name,
        action.id,
        action.user_id,
        action.family_id,
        run.status,
        action.schedule_kind,
        action.output_mode,
        action.language,
        action.timezone,
        run.model_used,
        fallback_used,
        run.tokens_used,
        run.duration_ms,
        run.error_code,
        failed_sources,
        len(action.sources or []),
    )


async def _resolve_telegram_id(session, user_id):  # noqa: ANN001
    return await session.scalar(select(User.telegram_id).where(User.id == user_id))


def _build_action_buttons(action: ScheduledAction) -> list[dict]:
    from src.core.scheduled_actions.message_builder import build_action_buttons

    return build_action_buttons(action)


async def _send_action_message(
    telegram_id: int,
    text: str,
    *,
    buttons: list[dict] | None = None,
    photo: bytes | None = None,
) -> None:
    from src.core.scheduled_actions.message_builder import send_action_message

    await send_action_message(telegram_id, text, buttons=buttons, photo=photo)


async def _notify_auto_completed(session, action: ScheduledAction) -> None:  # noqa: ANN001
    telegram_id = await _resolve_telegram_id(session, action.user_id)
    if telegram_id is None:
        return

    text = t("sched_auto_completed", action.language or "en", title=action.title)
    try:
        await _send_action_message(telegram_id, text)
    except Exception:
        logger.exception("SIA auto-complete notification failed for action %s", action.id)


async def _notify_auto_paused(session, action: ScheduledAction) -> None:  # noqa: ANN001
    telegram_id = await _resolve_telegram_id(session, action.user_id)
    if telegram_id is None:
        return

    text = t(
        "sched_auto_paused",
        action.language or "en",
        title=action.title,
        failures=action.failure_count,
    )
    try:
        await _send_action_message(telegram_id, text)
    except Exception:
        logger.exception("SIA auto-pause notification failed for action %s", action.id)


@broker.task(schedule=[{"cron": "* * * * *"}])
async def dispatch_scheduled_actions() -> None:
    """Fetch due scheduled actions and execute them."""
    if not settings.ff_scheduled_actions:
        return

    now = now_utc()
    async with async_session() as session:
        result = await session.execute(
            select(ScheduledAction)
            .join(User, User.id == ScheduledAction.user_id)
            .where(
                ScheduledAction.status == ActionStatus.active,
                ScheduledAction.next_run_at <= now,
                User.telegram_id.is_not(None),
                User.onboarded.is_(True),
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
                if action.status == ActionStatus.paused:
                    await _notify_auto_paused(session, action)
        await session.commit()


def _extract_budget_data(finance_text: str) -> tuple[float, float] | None:
    """Parse 'This month: $X total' and 'Monthly budget: $Y' from finance data."""
    import re

    spent = 0.0
    budget = 0.0

    m_spent = re.search(
        r"(?:this month|este mes|за месяц)\s*:\s*\$?\s*([\d,.]+)",
        finance_text,
        flags=re.IGNORECASE,
    )
    if m_spent:
        spent = float(m_spent.group(1).replace(",", ""))

    m_budget = re.search(
        r"(?:monthly budget|presupuesto mensual|месячн\w*\s+бюджет)\s*:\s*\$?\s*([\d,.]+)",
        finance_text,
        flags=re.IGNORECASE,
    )
    if m_budget:
        budget = float(m_budget.group(1).replace(",", ""))

    if budget > 0:
        return spent, budget
    return None


async def _execute_action(session, action: ScheduledAction, now: datetime) -> None:  # noqa: ANN001
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

    _log_action_triggered(action)

    if is_action_completed(action, now):
        run.status = RunStatus.success
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        complete_action(action)
        await _notify_auto_completed(session, action)
        _log_run_event("scheduled_action_auto_completed", action, run)
        return

    telegram_id = await _resolve_telegram_id(session, action.user_id)
    if telegram_id is None:
        run.status = RunStatus.failed
        run.error_code = "no_telegram_id"
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        apply_failure(action, now)
        _log_run_event("scheduled_action_run_failed", action, run)
        return

    comm_mode = await get_communication_mode(str(action.user_id))
    if comm_mode == "silent":
        run.status = RunStatus.skipped
        run.error_code = "comm_mode_silent"
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        apply_success(action, now)
        _log_run_event("scheduled_action_run_skipped", action, run)
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
        _log_run_event("scheduled_action_run_skipped", action, run)
        return

    payload, sources_status = await collect_sources(action)

    # Epic G3: Check if action is completed via condition (e.g. sources are empty)
    if is_action_completed(action, now, payload=payload):
        run.status = RunStatus.success
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        complete_action(action)
        await _notify_auto_completed(session, action)
        _log_run_event("scheduled_action_auto_completed", action, run)
        return

    message_text, model_used, tokens_used, fallback_used = await format_action_message(
        action,
        payload,
        sources_status=sources_status,
        allow_synthesis=settings.ff_sia_synthesis,
    )
    buttons = _build_action_buttons(action)

    # Epic G2: Generate visual budget card if money_summary is present
    photo_bytes = None
    finance_text = payload.get("money_summary")
    if finance_text:
        budget_data = _extract_budget_data(finance_text)
        if budget_data:
            try:
                spent, budget = budget_data
                buf = generate_budget_card(spent, budget, language=action.language or "en")
                photo_bytes = buf.getvalue()
            except Exception:
                logger.exception("Failed to generate budget card for action %s", action.id)

    try:
        await _send_action_message(telegram_id, message_text, buttons=buttons, photo=photo_bytes)
    except Exception as exc:
        run.status = RunStatus.failed
        run.error_code = "send_failed"
        run.error_text = str(exc)[:500]
        run.sources_status = sources_status
        run.payload_snapshot = payload
        run.model_used = model_used
        run.tokens_used = tokens_used
        run.finished_at = now_utc()
        run.duration_ms = _run_duration_ms(run)
        apply_failure(action, now)
        if action.status == ActionStatus.paused:
            await _notify_auto_paused(session, action)
        _log_run_event(
            "scheduled_action_run_failed",
            action,
            run,
            fallback_used=fallback_used,
        )
        return

    run.status = RunStatus.partial if _has_failed_sources(sources_status) else RunStatus.success
    run.sources_status = sources_status
    run.payload_snapshot = payload
    run.message_preview = message_text[:500]
    run.model_used = model_used
    run.tokens_used = tokens_used
    run.finished_at = now_utc()
    run.duration_ms = _run_duration_ms(run)

    was_completed = action.status == ActionStatus.completed
    apply_success(action, now, payload=payload)
    if not was_completed and action.status == ActionStatus.completed:
        await _notify_auto_completed(session, action)

    event_name = (
        "scheduled_action_run_partial"
        if run.status == RunStatus.partial
        else "scheduled_action_run_succeeded"
    )
    _log_run_event(event_name, action, run, fallback_used=fallback_used)


RUN_RETENTION_DAYS = 90


@broker.task(schedule=[{"cron": "0 4 * * *"}])
async def cleanup_old_scheduled_action_runs() -> None:
    """Delete scheduled_action_runs older than 90 days for completed/deleted actions."""
    from sqlalchemy import and_, delete

    cutoff = now_utc() - timedelta(days=RUN_RETENTION_DAYS)
    async with async_session() as session:
        stmt = (
            delete(ScheduledActionRun)
            .where(
                and_(
                    ScheduledActionRun.created_at < cutoff,
                    ScheduledActionRun.scheduled_action_id.in_(
                        select(ScheduledAction.id).where(
                            ScheduledAction.status.in_([
                                ActionStatus.completed,
                                ActionStatus.deleted,
                            ])
                        )
                    ),
                )
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        logger.info("SIA cleanup: deleted %d old run records", result.rowcount)
