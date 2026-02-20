"""Day plan skill — create a prioritized list of tasks for the day."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.life_helpers import get_communication_mode, save_life_event
from src.core.models.enums import LifeEventType
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DAY_PLAN_SYSTEM_PROMPT = """Ты помогаешь пользователю спланировать день.
Извлеки список задач из сообщения. Первая задача = top1 (главный приоритет),
остальные = normal."""


class DayPlanSkill:
    name = "day_plan"
    intents = ["day_plan"]
    model = "gpt-5.2"

    @observe(name="day_plan")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = message.text or ""

        # Extract tasks from intent_data or parse from text
        tasks: list[str] = intent_data.get("tasks", [])

        if not tasks and text.strip():
            # Parse tasks from text: split by newlines, commas, or numbered list
            raw = text.strip()
            # Try splitting by newlines first
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            if len(lines) > 1:
                tasks = self._clean_task_lines(lines)
            else:
                # Try comma-separated
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                if len(parts) > 1:
                    tasks = parts
                else:
                    # Single task
                    tasks = [raw]

        if not tasks:
            return SkillResult(
                response_text="Какие задачи на сегодня? Перечислите через запятую или по строкам."
            )

        # Save each task as a separate LifeEvent
        saved_tasks: list[str] = []
        for i, task_text in enumerate(tasks):
            priority = "top1" if i == 0 else "normal"
            data = {"priority": priority, "order": i + 1, "done": False}

            await save_life_event(
                family_id=context.family_id,
                user_id=context.user_id,
                event_type=LifeEventType.task,
                text=task_text,
                data=data,
            )

            marker = "\U0001f525" if priority == "top1" else "\u2022"
            saved_tasks.append(f"{marker} {task_text}")

        plan_text = "\n".join(saved_tasks)

        mode = await get_communication_mode(context.user_id)
        if mode == "silent":
            return SkillResult(response_text="")
        elif mode == "coaching":
            return SkillResult(
                response_text=f"<b>План на день:</b>\n{plan_text}"
                f"\n\n\U0001f4a1 Фокус на первой задаче — остальное подождёт."
            )
        else:
            return SkillResult(response_text=f"<b>План на день:</b>\n{plan_text}")

    @staticmethod
    def _clean_task_lines(lines: list[str]) -> list[str]:
        """Remove numbering prefixes like '1.', '1)', '- ' from task lines."""
        cleaned: list[str] = []
        for line in lines:
            stripped = line.lstrip("0123456789.-) ").strip()
            if stripped:
                cleaned.append(stripped)
        return cleaned

    def get_system_prompt(self, context: SessionContext) -> str:
        return DAY_PLAN_SYSTEM_PROMPT


skill = DayPlanSkill()
