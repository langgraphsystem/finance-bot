"""Create task skill — add a task via natural language."""

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

CREATE_TASK_SYSTEM_PROMPT = """\
You help users create tasks and to-do items from natural language.
Extract the task title, priority, and deadline.
Respond in the user's preferred language: {language}.
If no preference is set, detect and match the language of their message."""

PRIORITY_KEYWORDS = {
    "urgent": TaskPriority.urgent,
    "срочно": TaskPriority.urgent,
    "high": TaskPriority.high,
    "важно": TaskPriority.high,
    "важный": TaskPriority.high,
    "low": TaskPriority.low,
    "низкий": TaskPriority.low,
    "неважно": TaskPriority.low,
}


def _parse_priority(intent_data: dict[str, Any], text: str) -> TaskPriority:
    """Extract priority from intent_data or text keywords."""
    if intent_data.get("task_priority"):
        raw = intent_data["task_priority"].lower().strip()
        try:
            return TaskPriority(raw)
        except ValueError:
            pass
        if raw in PRIORITY_KEYWORDS:
            return PRIORITY_KEYWORDS[raw]

    text_lower = text.lower()
    for keyword, priority in PRIORITY_KEYWORDS.items():
        if keyword in text_lower:
            return priority

    return TaskPriority.medium


def _parse_deadline(intent_data: dict[str, Any], timezone: str) -> datetime | None:
    """Parse deadline from intent_data."""
    raw = intent_data.get("task_deadline") or intent_data.get("date")
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


class CreateTaskSkill:
    name = "create_task"
    intents = ["create_task"]
    model = "claude-haiku-4-5"

    @observe(name="create_task")
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
            return SkillResult(response_text="What task do you want to add?")

        priority = _parse_priority(intent_data, message.text or "")
        deadline = _parse_deadline(intent_data, context.timezone)

        task = Task(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            title=title,
            status=TaskStatus.pending,
            priority=priority,
            due_at=deadline,
            domain="tasks",
            source_message_id=message.id,
        )

        await save_task(task)

        parts = [f"Added: {title}"]
        if priority != TaskPriority.medium:
            parts[0] += f" ({priority.value} priority)"
        if deadline:
            parts.append(f"Due: {deadline.strftime('%b %d, %I:%M %p')}")

        return SkillResult(response_text="\n".join(parts))

    def get_system_prompt(self, context: SessionContext) -> str:
        return CREATE_TASK_SYSTEM_PROMPT.format(language=context.language or "en")


async def save_task(task: Task) -> None:
    """Persist a task to the database."""
    async with async_session() as session:
        session.add(task)
        await session.commit()


skill = CreateTaskSkill()
