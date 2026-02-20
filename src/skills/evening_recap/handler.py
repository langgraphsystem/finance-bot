"""Evening recap orchestrator — summarizes the day's activity.

Same parallel-collection pattern as morning_brief but with a
wrap-up tone: tasks completed, money spent, events attended.
"""

import asyncio
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import generate_text
from src.core.models.enums import TaskStatus, TransactionType
from src.core.models.task import Task
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.core.plugin_loader import plugin_loader
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

COLLECTOR_TIMEOUT_S = 3.0

_DEFAULT_SYSTEM_PROMPT = """\
You generate an evening recap for the user.
You receive real data about completed tasks, spending, and events.
Synthesize it into a short wrap-up message.

Rules:
- Warm wrap-up tone — not action items, just a summary.
- Bullet points, short lines.
- Skip sections that have no data.
- End with something encouraging if it was productive.
- Max 8 bullet points total.
- Use HTML tags for Telegram (<b>, <i>). No Markdown.
- Respond in: {language}."""


class EveningRecapSkill:
    name = "evening_recap"
    intents = ["evening_recap"]
    model = "claude-sonnet-4-6"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(
            user_name=context.user_profile.get("name", ""),
            language=context.language or "en",
        )

    @observe(name="evening_recap")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        plugin = plugin_loader.load(context.business_type)
        sections = plugin.evening_recap_sections

        collectors: dict[str, Any] = {
            "completed_tasks": self._collect_completed_tasks(context),
            "completed_jobs": self._collect_completed_tasks(context),
            "spending_total": self._collect_spending(context),
            "invoices_sent": self._collect_invoices_sent(context),
        }

        active = {k: v for k, v in collectors.items() if k in sections}

        if not active:
            return SkillResult(response_text="Your evening recap has no sections configured.")

        results = await asyncio.gather(
            *(asyncio.wait_for(coro, timeout=COLLECTOR_TIMEOUT_S) for coro in active.values()),
            return_exceptions=True,
        )

        data: dict[str, str] = {}
        for key, result in zip(active.keys(), results):
            if isinstance(result, Exception):
                logger.warning("Evening recap collector '%s' failed: %s", key, result)
            elif result:
                data[key] = result

        if not data:
            return SkillResult(response_text="Not much to recap today. Rest up!")

        recap = await self._synthesize(data, context)
        return SkillResult(response_text=recap)

    # ------------------------------------------------------------------
    # Collectors
    # ------------------------------------------------------------------
    async def _collect_completed_tasks(self, ctx: SessionContext) -> str:
        today = date.today()
        async with async_session() as session:
            result = await session.execute(
                select(Task)
                .where(
                    Task.family_id == uuid.UUID(ctx.family_id),
                    Task.user_id == uuid.UUID(ctx.user_id),
                    Task.status == TaskStatus.done,
                    Task.completed_at >= today,
                )
                .limit(10)
            )
            tasks = list(result.scalars().all())

        if not tasks:
            return ""

        lines = [f"- {t.title}" for t in tasks]
        return f"Completed today ({len(tasks)}):\n" + "\n".join(lines)

    async def _collect_spending(self, ctx: SessionContext) -> str:
        today = date.today()
        async with async_session() as session:
            result = await session.execute(
                select(func.sum(Transaction.amount), func.count(Transaction.id)).where(
                    Transaction.family_id == uuid.UUID(ctx.family_id),
                    Transaction.date >= today,
                    Transaction.type == TransactionType.expense,
                )
            )
            row = result.one_or_none()

        if not row or not row[0]:
            return ""

        total = float(row[0])
        count = row[1]
        return f"Spending today:\n- ${total:.2f} across {count} transactions"

    async def _collect_invoices_sent(self, ctx: SessionContext) -> str:
        """Placeholder for invoice tracking — returns empty for now."""
        return ""

    # ------------------------------------------------------------------
    # LLM synthesis
    # ------------------------------------------------------------------
    async def _synthesize(self, data: dict[str, str], ctx: SessionContext) -> str:
        combined = "\n\n".join(f"[{key}]\n{text}" for key, text in data.items())
        system = self.get_system_prompt(ctx)

        try:
            return await generate_text(
                self.model, system,
                [{"role": "user", "content": combined}],
                max_tokens=1024,
            )
        except Exception as e:
            logger.warning("Evening recap synthesis failed: %s", e)
            return "Couldn't prepare your evening recap."


skill = EveningRecapSkill()
