"""Reminder dispatch cron task — sends due reminders via Telegram.

Supports one-shot and recurring (daily/weekly/monthly) reminders.
Recurring reminders advance reminder_at to the next occurrence after firing.
"""

import logging
from calendar import monthrange
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from src.core.db import async_session
from src.core.models.enums import ReminderRecurrence, TaskStatus
from src.core.models.task import Task
from src.core.models.user import User
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)

_RECURRENCE_LABELS = {
    ReminderRecurrence.daily: "daily",
    ReminderRecurrence.weekly: "weekly",
    ReminderRecurrence.monthly: "monthly",
}


async def _send_telegram_message(telegram_id: int, text: str) -> None:
    """Send a message via Telegram Bot API."""
    from src.core.config import settings

    try:
        from aiogram import Bot

        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception as e:
        logger.error("Failed to send reminder to %s: %s", telegram_id, e)


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


@broker.task(schedule=[{"cron": "* * * * *"}])  # Every minute
async def dispatch_due_reminders() -> None:
    """Check for due reminders and send them via Telegram."""
    now = datetime.now(UTC)

    async with async_session() as session:
        # Find all pending tasks with reminder_at <= now
        result = await session.execute(
            select(Task, User.telegram_id)
            .join(User, Task.user_id == User.id)
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
        for task, telegram_id in due_tasks:
            try:
                text = f"🔔 <b>Напоминание</b>\n\n{task.title}"
                if task.description:
                    text += f"\n\n{task.description}"
                if (
                    task.recurrence
                    and task.recurrence != ReminderRecurrence.none
                ):
                    label = _RECURRENCE_LABELS.get(task.recurrence, task.recurrence.value)
                    text += f"\n\n<i>🔁 Repeats {label}</i>"

                await _send_telegram_message(telegram_id, text)
                sent_ids.append((task, telegram_id))
                logger.info("Reminder sent: task %s to user %s", task.id, telegram_id)
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
