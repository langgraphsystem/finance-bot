"""List tasks skill — show open tasks for the user."""

import logging
import uuid
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import TaskPriority, TaskStatus
from src.core.models.task import Task
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

LIST_TASKS_SYSTEM_PROMPT = """\
You help users view their task list.
ALWAYS respond in the same language as the user's message/query.
If no preference is set, detect and match the language of their message."""

PRIORITY_ICONS = {
    TaskPriority.urgent: "[urgent]",
    TaskPriority.high: "[high]",
    TaskPriority.medium: "",
    TaskPriority.low: "[low]",
}


class ListTasksSkill:
    name = "list_tasks"
    intents = ["list_tasks"]
    model = "gpt-5.2"

    @observe(name="list_tasks")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        tasks = await get_open_tasks(context.family_id, context.user_id)

        if not tasks:
            return SkillResult(response_text="No open tasks. Text me to add one.")

        lines = [f"Your tasks ({len(tasks)} open):"]
        for i, t in enumerate(tasks, 1):
            icon = PRIORITY_ICONS.get(t.priority, "")
            prefix = f"{icon} " if icon else ""
            due = ""
            if t.due_at:
                due = f" — due {t.due_at.strftime('%b %d, %I:%M %p')}"
            lines.append(f"{i}. {prefix}{t.title}{due}")

        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        return LIST_TASKS_SYSTEM_PROMPT.format(language=context.language or "en")


async def get_open_tasks(family_id: str, user_id: str) -> list[Task]:
    """Fetch open tasks ordered by priority then due date."""
    priority_order = {
        TaskPriority.urgent: 0,
        TaskPriority.high: 1,
        TaskPriority.medium: 2,
        TaskPriority.low: 3,
    }
    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .where(
                Task.family_id == uuid.UUID(family_id),
                Task.user_id == uuid.UUID(user_id),
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            )
            .order_by(Task.due_at.asc().nulls_last())
        )
        tasks = list(result.scalars().all())

    tasks.sort(key=lambda t: priority_order.get(t.priority, 2))
    return tasks


skill = ListTasksSkill()
