"""Scheduled Intelligence Actions — dispatcher cron task.

Runs every minute, fetches due actions with FOR UPDATE SKIP LOCKED,
executes collectors, formats output, and sends via Telegram.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session
from src.core.models.enums import ActionStatus, RunStatus
from src.core.models.scheduled_action import ScheduledAction
from src.core.models.scheduled_action_run import ScheduledActionRun
from src.core.models.user import User
from src.core.notifications_pkg.dispatch import send_telegram_message
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)

DISPATCH_BATCH_LIMIT = 50


@broker.task(schedule=[{"cron": "* * * * *"}])
async def dispatch_scheduled_actions() -> None:
    """Fetch due scheduled actions and execute them."""
    if not settings.ff_scheduled_actions:
        return

    now = datetime.now(UTC)

    async with async_session() as session:
        # Fetch due actions with row-level lock (multi-worker safe)
        result = await session.execute(
            select(ScheduledAction)
            .where(
                ScheduledAction.status == ActionStatus.active,
                ScheduledAction.next_run_at <= now,
            )
            .with_for_update(skip_locked=True)
            .limit(DISPATCH_BATCH_LIMIT)
        )
        due_actions = result.scalars().all()

        if not due_actions:
            return

        logger.info("SIA dispatcher: %d due actions found", len(due_actions))

        for action in due_actions:
            try:
                await _execute_action(session, action, now)
            except Exception:
                logger.exception(
                    "SIA dispatch failed for action %s (user %s)",
                    action.id,
                    action.user_id,
                )
                action.failure_count += 1
                if action.failure_count >= action.max_failures:
                    action.status = ActionStatus.paused
                    logger.warning(
                        "SIA action %s auto-paused after %d failures",
                        action.id,
                        action.failure_count,
                    )

        await session.commit()


async def _execute_action(
    session,  # noqa: ANN001
    action: ScheduledAction,
    now: datetime,
) -> None:
    """Execute a single scheduled action: collect data, format, send."""
    # Check end conditions
    if action.max_runs and action.run_count >= action.max_runs:
        action.status = ActionStatus.completed
        action.next_run_at = None
        return

    if action.end_at and now >= action.end_at:
        action.status = ActionStatus.completed
        action.next_run_at = None
        return

    # Create idempotent run record
    run = ScheduledActionRun(
        scheduled_action_id=action.id,
        planned_run_at=action.next_run_at,
        started_at=now,
        status=RunStatus.running,
    )
    session.add(run)
    try:
        await session.flush()
    except Exception:
        # Duplicate run (unique constraint) — skip
        logger.info("SIA run already exists for action %s at %s", action.id, action.next_run_at)
        await session.rollback()
        return

    # Resolve user telegram_id
    user_result = await session.execute(
        select(User.telegram_id).where(User.id == action.user_id)
    )
    telegram_id = user_result.scalar_one_or_none()
    if not telegram_id:
        run.status = RunStatus.failed
        run.error_code = "no_telegram_id"
        run.finished_at = datetime.now(UTC)
        _advance_action(action, now)
        return

    # Build message (compact mode — template, no LLM)
    message_text = _build_compact_message(action)

    # Send
    try:
        await send_telegram_message(telegram_id, message_text)
        run.status = RunStatus.success
        run.message_preview = message_text[:500]
        action.failure_count = 0
        action.last_success_at = datetime.now(UTC)
    except Exception as exc:
        run.status = RunStatus.failed
        run.error_code = "send_failed"
        run.error_text = str(exc)[:500]
        action.failure_count += 1
        if action.failure_count >= action.max_failures:
            action.status = ActionStatus.paused

    run.finished_at = datetime.now(UTC)
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    _advance_action(action, now)


def _advance_action(action: ScheduledAction, now: datetime) -> None:
    """Advance next_run_at based on schedule_kind, increment run_count."""
    from src.core.models.enums import ScheduleKind

    action.last_run_at = now
    action.run_count += 1

    if action.schedule_kind == ScheduleKind.once:
        action.next_run_at = None
        action.status = ActionStatus.completed
        return

    # For recurring: compute next run (placeholder — full implementation in engine.py)
    from datetime import timedelta

    if action.schedule_kind == ScheduleKind.daily:
        action.next_run_at = action.next_run_at + timedelta(days=1)
    elif action.schedule_kind == ScheduleKind.weekly:
        action.next_run_at = action.next_run_at + timedelta(weeks=1)
    elif action.schedule_kind == ScheduleKind.monthly:
        from calendar import monthrange

        cur = action.next_run_at
        year = cur.year + (cur.month // 12)
        month = (cur.month % 12) + 1
        day = min(cur.day, monthrange(year, month)[1])
        action.next_run_at = cur.replace(year=year, month=month, day=day)
    elif action.schedule_kind == ScheduleKind.weekdays:
        delta = timedelta(days=1)
        nxt = action.next_run_at + delta
        while nxt.weekday() >= 5:  # Skip Sat(5), Sun(6)
            nxt += delta
        action.next_run_at = nxt
    else:
        # Fallback: advance by 1 day
        action.next_run_at = action.next_run_at + timedelta(days=1)

    # Check if end condition reached after advancement
    if action.max_runs and action.run_count >= action.max_runs:
        action.status = ActionStatus.completed
        action.next_run_at = None

    if action.end_at and action.next_run_at and action.next_run_at >= action.end_at:
        action.status = ActionStatus.completed
        action.next_run_at = None


def _build_compact_message(action: ScheduledAction) -> str:
    """Build a compact HTML message for the scheduled action (no LLM)."""
    lang = action.language or "en"

    greetings_map = {
        "en": {0: "Good morning", 1: "Good afternoon", 2: "Good evening"},
        "ru": {0: "Доброе утро", 1: "Добрый день", 2: "Добрый вечер"},
        "es": {0: "Buenos días", 1: "Buenas tardes", 2: "Buenas noches"},
    }
    emoji_map = {0: "☀️", 1: "🌤", 2: "🌙"}

    # Determine time of day
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(action.timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = datetime.now(tz)
    if local_now.hour < 12:
        tod = 0
    elif local_now.hour < 18:
        tod = 1
    else:
        tod = 2

    greetings = greetings_map.get(lang, greetings_map["en"])
    emoji = emoji_map[tod]
    greeting = greetings[tod]

    lines = [f"{emoji} <b>{greeting}!</b>", ""]

    # Show action title
    lines.append(f"📌 <b>{action.title}</b>")
    lines.append("")

    # Show instruction/description
    if action.instruction:
        lines.append(action.instruction[:300])
        lines.append("")

    # Source placeholders (actual data collection in Phase 2)
    source_icons = {
        "calendar": "📅",
        "tasks": "✅",
        "money_summary": "💰",
        "email_highlights": "📧",
        "outstanding": "🔴",
    }
    source_names = {
        "en": {
            "calendar": "Calendar", "tasks": "Tasks", "money_summary": "Money",
            "email_highlights": "Email", "outstanding": "Outstanding",
        },
        "ru": {
            "calendar": "Календарь", "tasks": "Задачи", "money_summary": "Финансы",
            "email_highlights": "Почта", "outstanding": "Неоплаченные",
        },
        "es": {
            "calendar": "Calendario", "tasks": "Tareas", "money_summary": "Finanzas",
            "email_highlights": "Correo", "outstanding": "Pendientes",
        },
    }
    names = source_names.get(lang, source_names["en"])
    sources = action.sources or []
    if sources:
        source_parts = []
        for s in sources:
            icon = source_icons.get(s, "📋")
            name = names.get(s, s)
            source_parts.append(f"{icon} {name}")
        lines.append(f"<i>{'  '.join(source_parts)}</i>")

    return "\n".join(lines)
