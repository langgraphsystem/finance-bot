"""Reminder dispatch cron task — sends due reminders via Telegram.

Supports one-shot and recurring (daily/weekly/monthly) reminders.
Recurring reminders advance reminder_at to the next occurrence after firing.
"""

import logging
from calendar import monthrange
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from src.core.config import settings
from src.core.db import async_session
from src.core.locale_resolution import resolve_notification_locale
from src.core.models.enums import ReminderRecurrence, TaskStatus
from src.core.models.task import Task
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.notifications_pkg.dispatch import send_telegram_message
from src.core.notifications_pkg.templates import get_reminder_label
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)

_RECURRENCE_LABELS = {
    ReminderRecurrence.daily: "daily",
    ReminderRecurrence.weekly: "weekly",
    ReminderRecurrence.monthly: "monthly",
}



def _compute_next_reminder(task: Task, now: datetime) -> datetime | None:
    """Compute the next reminder_at based on recurrence and original_reminder_time."""
    if task.recurrence == ReminderRecurrence.daily:
        delta = timedelta(days=1)
    elif task.recurrence == ReminderRecurrence.weekly:
        delta = timedelta(weeks=1)
    elif task.recurrence == ReminderRecurrence.monthly:
        current = task.reminder_at
        # Advance to next month, clamping day for short months
        year = current.year + (current.month // 12)
        month = (current.month % 12) + 1
        day = min(current.day, monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)
    else:
        return None

    next_at = task.reminder_at + delta

    # Preserve original wall-clock time (DST-safe)
    if task.original_reminder_time:
        try:
            hour, minute = map(int, task.original_reminder_time.split(":"))
            next_at = next_at.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, AttributeError):
            pass

    return next_at


def _extract_due_row(row: tuple) -> dict[str, str | int | Task | None]:
    """Extract reminder row fields, keeping backward compatibility in tests."""
    task = row[0]
    telegram_id = row[1] if len(row) > 1 else None
    legacy_language = row[2] if len(row) > 2 else None
    user_id = str(row[3]) if len(row) > 3 and row[3] else None
    user_language = row[4] if len(row) > 4 else None
    preferred_language = row[5] if len(row) > 5 else None
    notification_language = row[6] if len(row) > 6 else None
    timezone = row[7] if len(row) > 7 else None
    timezone_source = row[8] if len(row) > 8 else None

    return {
        "task": task,
        "telegram_id": telegram_id,
        "legacy_language": legacy_language,
        "user_id": user_id,
        "user_language": user_language,
        "preferred_language": preferred_language,
        "notification_language": notification_language,
        "timezone": timezone,
        "timezone_source": timezone_source,
    }


@broker.task(schedule=[{"cron": "* * * * *"}])  # Every minute
async def dispatch_due_reminders() -> None:
    """Check for due reminders and send them via Telegram."""
    now = datetime.now(UTC)

    async with async_session() as session:
        # Find all pending tasks with reminder_at <= now
        result = await session.execute(
            select(
                Task,
                User.telegram_id,
                func.coalesce(UserProfile.preferred_language, User.language).label("language"),
                User.id.label("user_id"),
                User.language.label("user_language"),
                UserProfile.preferred_language,
                UserProfile.notification_language,
                UserProfile.timezone,
                UserProfile.timezone_source,
            )
            .join(User, Task.user_id == User.id)
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .where(
                Task.reminder_at <= now,
                Task.status == TaskStatus.pending,
                Task.reminder_at.isnot(None),
            )
            .limit(100)
        )
        due_tasks = result.all()

        if not due_tasks:
            return

        sent_ids: list[tuple] = []  # (task, telegram_id)
        language_stats: dict[str, int] = {}
        for row in due_tasks:
            try:
                fields = _extract_due_row(row)
                task = fields["task"]
                telegram_id = fields["telegram_id"]
                if telegram_id is None:
                    logger.warning("Skipping reminder %s: missing telegram_id", task.id)
                    continue

                resolved = resolve_notification_locale(
                    user_language=fields["user_language"] or fields["legacy_language"],
                    preferred_language=fields["preferred_language"],
                    notification_language=fields["notification_language"],
                    timezone=fields["timezone"],
                    timezone_source=fields["timezone_source"],
                    use_v2_read=settings.ff_locale_v2_read,
                    prefer_user_on_desync=True,
                )
                language = resolved.language
                language_source = resolved.language_source
                timezone = resolved.timezone
                timezone_source = resolved.timezone_source

                label = get_reminder_label(language)
                text = f"\U0001f514 <b>{label}</b>\n\n{task.title}"
                if task.description:
                    text += f"\n\n{task.description}"
                if (
                    task.recurrence
                    and task.recurrence != ReminderRecurrence.none
                ):
                    label = _RECURRENCE_LABELS.get(task.recurrence, task.recurrence.value)
                    text += f"\n\n<i>🔁 Repeats {label}</i>"

                await send_telegram_message(telegram_id, text)
                sent_ids.append((task, telegram_id))
                language_stats[language] = language_stats.get(language, 0) + 1
                logger.info(
                    "Reminder sent: task_id=%s telegram_id=%s user_id=%s language=%s "
                    "language_source=%s timezone=%s timezone_source=%s ff_locale_v2_read=%s",
                    task.id,
                    telegram_id,
                    fields["user_id"],
                    language,
                    language_source,
                    timezone,
                    timezone_source,
                    settings.ff_locale_v2_read,
                )
            except Exception as e:
                logger.error("Failed to dispatch reminder %s: %s", task.id, e)

        if not sent_ids:
            return

        # Separate one-shot vs recurring
        one_shot_ids = []
        recurring_tasks = []
        for task, _ in sent_ids:
            if task.recurrence and task.recurrence != ReminderRecurrence.none:
                recurring_tasks.append(task)
            else:
                one_shot_ids.append(task.id)

        # Mark one-shot reminders as done
        if one_shot_ids:
            await session.execute(
                update(Task)
                .where(Task.id.in_(one_shot_ids))
                .values(status=TaskStatus.done, completed_at=now)
            )

        # Advance recurring reminders to next occurrence
        for task in recurring_tasks:
            next_at = _compute_next_reminder(task, now)
            if next_at and (not task.recurrence_end_at or next_at <= task.recurrence_end_at):
                await session.execute(
                    update(Task)
                    .where(Task.id == task.id)
                    .values(reminder_at=next_at, due_at=next_at)
                )
                logger.info(
                    "Recurring reminder %s advanced to %s", task.id, next_at
                )
            else:
                # Recurrence ended
                await session.execute(
                    update(Task)
                    .where(Task.id == task.id)
                    .values(status=TaskStatus.done, completed_at=now)
                )
                logger.info("Recurring reminder %s ended (past end date)", task.id)

        await session.commit()
        logger.info(
            "Processed %d reminders (%d one-shot, %d recurring)",
            len(sent_ids),
            len(one_shot_ids),
            len(recurring_tasks),
        )
        logger.info(
            "Reminder locale metrics: sent_total=%d by_language=%s ff_locale_v2_read=%s "
            "ff_reminder_dispatch_v2=%s",
            len(sent_ids),
            language_stats,
            settings.ff_locale_v2_read,
            settings.ff_reminder_dispatch_v2,
        )
