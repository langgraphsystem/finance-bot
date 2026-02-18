"""Reminder dispatch cron task — sends due reminders via Telegram."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update

from src.core.db import async_session
from src.core.models.enums import TaskStatus
from src.core.models.task import Task
from src.core.models.user import User
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


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

        sent_ids = []
        for task, telegram_id in due_tasks:
            try:
                text = f"🔔 <b>Напоминание</b>\n\n{task.title}"
                if task.description:
                    text += f"\n\n{task.description}"

                await _send_telegram_message(telegram_id, text)
                sent_ids.append(task.id)
                logger.info("Reminder sent: task %s to user %s", task.id, telegram_id)
            except Exception as e:
                logger.error("Failed to dispatch reminder %s: %s", task.id, e)

        # Mark sent reminders as done
        if sent_ids:
            await session.execute(
                update(Task)
                .where(Task.id.in_(sent_ids))
                .values(status=TaskStatus.done, completed_at=now)
            )
            await session.commit()
            logger.info("Marked %d reminders as done", len(sent_ids))
