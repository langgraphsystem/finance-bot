"""Complete task skill — mark a task as done."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import TaskStatus
from src.core.models.task import Task
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

COMPLETE_TASK_SYSTEM_PROMPT = """\
You help users mark tasks as done.
Respond in the user's preferred language: {language}.
If no preference is set, detect and match the language of their message."""


class CompleteTaskSkill:
    name = "complete_task"
    intents = ["complete_task"]
    model = "claude-haiku-4-5"

    @observe(name="complete_task")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = (
            intent_data.get("task_title")
            or intent_data.get("description")
            or message.text
            or ""
        )
        query = query.strip()

        if not query:
            return SkillResult(response_text="Which task did you complete?")

        task = await find_and_complete_task(
            context.family_id, context.user_id, query
        )

        if task is None:
            return SkillResult(
                response_text=f"No open task matching \"{query}\". Check your list?"
            )

        remaining = await count_open_tasks(context.family_id, context.user_id)
        return SkillResult(
            response_text=(
                f"Marked done: {task.title}. "
                f"{remaining} task{'s' if remaining != 1 else ''} left."
            )
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return COMPLETE_TASK_SYSTEM_PROMPT.format(language=context.language or "en")


async def find_and_complete_task(
    family_id: str, user_id: str, query: str
) -> Task | None:
    """Find the best matching open task and mark it done."""
    query_lower = query.lower()

    async with async_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.family_id == uuid.UUID(family_id),
                Task.user_id == uuid.UUID(user_id),
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            )
        )
        tasks = list(result.scalars().all())

    if not tasks:
        return None

    # Find best match: exact substring match first, then partial
    best = None
    best_score = -1
    for t in tasks:
        title_lower = t.title.lower()
        if query_lower == title_lower:
            best = t
            break
        if query_lower in title_lower:
            score = len(query_lower) / len(title_lower)
            if score > best_score:
                best_score = score
                best = t
        elif title_lower in query_lower:
            score = len(title_lower) / len(query_lower) * 0.8
            if score > best_score:
                best_score = score
                best = t

    if best is None:
        return None

    # Mark as done
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.id == best.id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.status = TaskStatus.done
            task.completed_at = datetime.now(UTC)
            await session.commit()
            return task
    return None


async def count_open_tasks(family_id: str, user_id: str) -> int:
    """Count remaining open tasks."""
    from sqlalchemy import func

    async with async_session() as session:
        result = await session.execute(
            select(func.count(Task.id)).where(
                Task.family_id == uuid.UUID(family_id),
                Task.user_id == uuid.UUID(user_id),
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            )
        )
        return result.scalar() or 0


skill = CompleteTaskSkill()
