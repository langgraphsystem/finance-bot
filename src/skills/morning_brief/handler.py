"""Morning brief orchestrator — parallel cross-domain data collection + LLM synthesis.

Phase 3.5 rewrite: collects real data from calendar, tasks, email, and
finance in parallel via ``asyncio.gather()``, then synthesizes a coherent
brief using Claude Sonnet.  Plugin bundles control which sections appear.

Graceful degradation: if a service is not connected or a collector times out,
that section is silently skipped.
"""

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from src.core.connectors import connector_registry
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.google_auth import parse_email_headers
from src.core.llm.clients import generate_text
from src.core.models.enums import TaskPriority, TaskStatus, TransactionType
from src.core.models.task import Task
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.core.plugin_loader import plugin_loader
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

# Per-collector timeout so one slow service doesn't block the whole brief.
COLLECTOR_TIMEOUT_S = 3.0

_DEFAULT_SYSTEM_PROMPT = """\
You generate a morning brief for the user.
You receive real data from calendar, tasks, email, and finance.
Synthesize it into one scannable message.

Rules:
- Start with a time-appropriate greeting.
- Use section headers with emoji for each domain that has data.
- Bullet points, short lines — scannable, not dense paragraphs.
- Skip sections that have no data (don't say "no data available").
- End with one actionable question.
- Max 12 bullet points total across all sections.
- Use HTML tags for Telegram (<b>, <i>). No Markdown.
- Respond in: {language}."""


class MorningBriefSkill:
    name = "morning_brief"
    intents = ["morning_brief"]
    model = "claude-sonnet-4-6"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(
            user_name=context.user_profile.get("name", ""),
            language=context.language or "en",
        )

    @observe(name="morning_brief")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        plugin = plugin_loader.load(context.business_type)
        sections = plugin.morning_brief_sections

        # Map section keys to coroutines
        collectors: dict[str, Any] = {
            "schedule": self._collect_events(context),
            "jobs_today": self._collect_events(context),
            "tasks": self._collect_tasks(context),
            "money_summary": self._collect_finance(context),
            "email_highlights": self._collect_emails(context),
            "outstanding": self._collect_outstanding(context),
        }

        # Only run sections configured in plugin
        active = {k: v for k, v in collectors.items() if k in sections}

        if not active:
            return SkillResult(response_text="Your morning brief has no sections configured.")

        results = await asyncio.gather(
            *(asyncio.wait_for(coro, timeout=COLLECTOR_TIMEOUT_S) for coro in active.values()),
            return_exceptions=True,
        )

        data: dict[str, str] = {}
        for key, result in zip(active.keys(), results):
            if isinstance(result, Exception):
                logger.warning("Morning brief collector '%s' failed: %s", key, result)
            elif result:
                data[key] = result

        if not data:
            return SkillResult(
                response_text="Couldn't load data for your morning brief. Try again later."
            )

        brief = await self._synthesize(data, context)
        return SkillResult(response_text=brief)

    # ------------------------------------------------------------------
    # Data collectors
    # ------------------------------------------------------------------
    async def _collect_events(self, ctx: SessionContext) -> str:
        google = connector_registry.get("google")
        if not google or not await google.is_connected(ctx.user_id):
            return ""

        client = await google.get_client(ctx.user_id)
        if not client:
            return ""

        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        events = await client.list_events(today_start, today_end)
        if not events:
            return ""

        lines = []
        for e in events[:8]:
            time_str = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "?"))
            summary = e.get("summary", "(no title)")
            lines.append(f"- {time_str}: {summary}")
        return "Today's calendar:\n" + "\n".join(lines)

    async def _collect_tasks(self, ctx: SessionContext) -> str:
        async with async_session() as session:
            result = await session.execute(
                select(Task)
                .where(
                    Task.family_id == uuid.UUID(ctx.family_id),
                    Task.user_id == uuid.UUID(ctx.user_id),
                    Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
                )
                .order_by(Task.due_at.asc().nulls_last())
                .limit(6)
            )
            tasks = list(result.scalars().all())

        if not tasks:
            return ""

        lines = []
        for t in tasks:
            priority = ""
            if t.priority in (TaskPriority.urgent, TaskPriority.high):
                priority = f"[{t.priority.value}] "
            due = ""
            if t.due_at:
                due = f" — due {t.due_at.strftime('%b %d')}"
            lines.append(f"- {priority}{t.title}{due}")
        return f"Open tasks ({len(tasks)}):\n" + "\n".join(lines)

    async def _collect_finance(self, ctx: SessionContext) -> str:
        today = date.today()
        yesterday = today - timedelta(days=1)

        async with async_session() as session:
            result = await session.execute(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == uuid.UUID(ctx.family_id),
                    Transaction.date >= yesterday,
                    Transaction.date < today,
                    Transaction.type == TransactionType.expense,
                )
            )
            yesterday_expense = float(result.scalar() or 0)

            result2 = await session.execute(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == uuid.UUID(ctx.family_id),
                    Transaction.date >= today.replace(day=1),
                    Transaction.type == TransactionType.expense,
                )
            )
            month_expense = float(result2.scalar() or 0)

        if yesterday_expense == 0 and month_expense == 0:
            return ""

        parts = []
        if yesterday_expense > 0:
            parts.append(f"Yesterday: ${yesterday_expense:.2f} spent")
        parts.append(f"This month: ${month_expense:.2f} total")
        return "Money:\n" + "\n".join(f"- {p}" for p in parts)

    async def _collect_emails(self, ctx: SessionContext) -> str:
        google = connector_registry.get("google")
        if not google or not await google.is_connected(ctx.user_id):
            return ""

        client = await google.get_client(ctx.user_id)
        if not client:
            return ""

        messages = await client.list_messages("is:unread is:important", max_results=5)
        if not messages:
            return ""

        parsed = [parse_email_headers(m) for m in messages]
        lines = [f"- {e['from']}: {e['subject']}" for e in parsed[:5]]
        return f"Unread emails ({len(parsed)}):\n" + "\n".join(lines)

    async def _collect_outstanding(self, ctx: SessionContext) -> str:
        """Collect overdue recurring payments / invoices."""
        from src.core.models.recurring_payment import RecurringPayment

        today = date.today()
        async with async_session() as session:
            result = await session.execute(
                select(RecurringPayment)
                .where(
                    RecurringPayment.family_id == uuid.UUID(ctx.family_id),
                    RecurringPayment.next_date < today,
                    RecurringPayment.is_active.is_(True),
                )
                .limit(5)
            )
            overdue = list(result.scalars().all())

        if not overdue:
            return ""

        lines = [f"- {r.name}: ${float(r.amount):.2f}" for r in overdue]
        return f"Overdue ({len(overdue)}):\n" + "\n".join(lines)

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
            logger.warning("Morning brief synthesis failed: %s", e)
            return "Couldn't prepare your morning brief."


skill = MorningBriefSkill()
