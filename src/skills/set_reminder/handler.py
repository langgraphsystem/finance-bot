"""Set reminder skill — create a task with a specific reminder time."""

import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import TaskPriority, TaskStatus
from src.core.models.task import Task
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SET_REMINDER_SYSTEM_PROMPT = """\
You help users set reminders. Extract the reminder text and time.
Respond in the user's preferred language: {language}.
If no preference is set, detect and match the language of their message."""


def _parse_reminder_time(
    intent_data: dict[str, Any], timezone: str
) -> datetime | None:
    """Parse reminder time from intent_data fields."""
    raw = (
        intent_data.get("task_deadline")
        or intent_data.get("event_datetime")
        or intent_data.get("date")
    )
    if not raw:
        return None
    try:
        tz = ZoneInfo(timezone)
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt
    except (ValueError, KeyError):
        return None


class SetReminderSkill:
    name = "set_reminder"
    intents = ["set_reminder"]
    model = "claude-haiku-4-5"

    @observe(name="set_reminder")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        title = (
            intent_data.get("task_title")
            or intent_data.get("description")
            or message.text
            or ""
        )
        title = title.strip()

        if not title:
            return SkillResult(response_text="What should I remind you about?")

        reminder_time = _parse_reminder_time(intent_data, context.timezone)

        task = Task(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            title=title,
            status=TaskStatus.pending,
            priority=TaskPriority.medium,
            due_at=reminder_time,
            reminder_at=reminder_time,
            domain="tasks",
            source_message_id=message.id,
        )

        await save_reminder(task)

        if reminder_time:
            time_str = reminder_time.strftime("%I:%M %p").lstrip("0")
            return SkillResult(
                response_text=f"Reminder set for {time_str}: {title}"
            )
        return SkillResult(
            response_text=f"Reminder saved: {title} (no specific time set)"
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SET_REMINDER_SYSTEM_PROMPT.format(language=context.language or "en")


async def save_reminder(task: Task) -> None:
    """Persist a reminder task to the database."""
    async with async_session() as session:
        session.add(task)
        await session.commit()


skill = SetReminderSkill()
