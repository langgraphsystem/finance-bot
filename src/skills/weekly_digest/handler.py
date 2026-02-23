"""Weekly digest skill — cross-domain summary of the past week.

Collects spending, tasks, life events, and upcoming calendar items,
then synthesizes via Claude Sonnet into a concise weekly report.
"""

import asyncio
import logging
import uuid
from datetime import date, timedelta
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
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

COLLECTOR_TIMEOUT_S = 4.0

_DEFAULT_SYSTEM_PROMPT = """\
You generate a weekly digest for the user.
You receive real data: spending totals, completed tasks, life events, and upcoming events.
Synthesize into a concise weekly summary.

Rules:
- Start with "Your week in review" or similar.
- Sections: Spending, Tasks, Life, Upcoming — skip any with no data.
- Bullet points, short lines. Max 12 bullet points total.
- End with an actionable question.
- Use HTML tags for Telegram (<b>, <i>). No Markdown.
- Respond in: {language}."""


class WeeklyDigestSkill:
    name = "weekly_digest"
    intents = ["weekly_digest"]
    model = "claude-sonnet-4-6"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(
            user_name=context.user_profile.get("name", ""),
            language=context.language or "en",
        )

    @observe(name="weekly_digest")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        today = date.today()
        week_ago = today - timedelta(days=7)

        collectors = {
            "spending": self._collect_spending(context, week_ago, today),
            "spending_by_category": self._collect_spending_by_category(
                context, week_ago, today
            ),
            "completed_tasks": self._collect_completed_tasks(
                context, week_ago, today
            ),
            "pending_tasks": self._collect_pending_tasks(context),
            "life_events": self._collect_life_events(context, week_ago, today),
            "upcoming_events": self._collect_upcoming_events(context, today),
        }

        results = await asyncio.gather(
            *(
                asyncio.wait_for(coro, timeout=COLLECTOR_TIMEOUT_S)
                for coro in collectors.values()
            ),
            return_exceptions=True,
        )

        data: dict[str, str] = {}
        for key, result in zip(collectors.keys(), results):
            if isinstance(result, Exception):
                logger.warning("Weekly digest collector '%s' failed: %s", key, result)
            elif result:
                data[key] = result

        if not data:
            return SkillResult(
                response_text=(
                    "Not much to report this week. "
                    "Start tracking expenses, tasks, or notes and "
                    "I'll have a full digest for you next Sunday."
                )
            )

        digest = await self._synthesize(data, context)
        return SkillResult(response_text=digest)

    # ------------------------------------------------------------------
    # Collectors
    # ------------------------------------------------------------------
    async def _collect_spending(
        self, ctx: SessionContext, date_from: date, date_to: date
    ) -> str:
        async with async_session() as session:
            result = await session.execute(
                select(
                    func.sum(Transaction.amount),
                    func.count(Transaction.id),
                ).where(
                    Transaction.family_id == uuid.UUID(ctx.family_id),
                    Transaction.date >= date_from,
                    Transaction.date <= date_to,
                    Transaction.type == TransactionType.expense,
                )
            )
            row = result.one_or_none()

        if not row or not row[0]:
            return ""

        total = float(row[0])
        count = row[1]

        # Compare with previous week
        prev_from = date_from - timedelta(days=7)
        async with async_session() as session:
            prev_result = await session.execute(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == uuid.UUID(ctx.family_id),
                    Transaction.date >= prev_from,
                    Transaction.date < date_from,
                    Transaction.type == TransactionType.expense,
                )
            )
            prev_row = prev_result.one_or_none()

        prev_total = float(prev_row[0]) if prev_row and prev_row[0] else 0
        comparison = ""
        if prev_total > 0:
            pct = ((total - prev_total) / prev_total) * 100
            direction = "up" if pct > 0 else "down"
            comparison = f" ({direction} {abs(pct):.0f}% vs last week)"

        return f"Total spending: ${total:,.2f} across {count} transactions{comparison}"

    async def _collect_spending_by_category(
        self, ctx: SessionContext, date_from: date, date_to: date
    ) -> str:
        async with async_session() as session:
            result = await session.execute(
                select(
                    Transaction.category,
                    func.sum(Transaction.amount),
                )
                .where(
                    Transaction.family_id == uuid.UUID(ctx.family_id),
                    Transaction.date >= date_from,
                    Transaction.date <= date_to,
                    Transaction.type == TransactionType.expense,
                )
                .group_by(Transaction.category)
                .order_by(func.sum(Transaction.amount).desc())
                .limit(5)
            )
            rows = result.all()

        if not rows:
            return ""

        lines = [f"- {cat or 'Other'}: ${float(amt):,.2f}" for cat, amt in rows]
        return "Top categories:\n" + "\n".join(lines)

    async def _collect_completed_tasks(
        self, ctx: SessionContext, date_from: date, date_to: date
    ) -> str:
        async with async_session() as session:
            result = await session.execute(
                select(func.count(Task.id)).where(
                    Task.family_id == uuid.UUID(ctx.family_id),
                    Task.user_id == uuid.UUID(ctx.user_id),
                    Task.status == TaskStatus.done,
                    Task.completed_at >= date_from,
                )
            )
            done_count = result.scalar() or 0

        if not done_count:
            return ""

        return f"Completed tasks: {done_count}"

    async def _collect_pending_tasks(self, ctx: SessionContext) -> str:
        async with async_session() as session:
            result = await session.execute(
                select(Task)
                .where(
                    Task.family_id == uuid.UUID(ctx.family_id),
                    Task.user_id == uuid.UUID(ctx.user_id),
                    Task.status == TaskStatus.pending,
                )
                .order_by(Task.due_at.asc().nullslast())
                .limit(5)
            )
            tasks = list(result.scalars().all())

        if not tasks:
            return ""

        lines = [f"- {t.title}" for t in tasks]
        return f"Pending tasks ({len(tasks)}):\n" + "\n".join(lines)

    async def _collect_life_events(
        self, ctx: SessionContext, date_from: date, date_to: date
    ) -> str:
        try:
            from src.core.life_helpers import query_life_events

            events = await query_life_events(
                family_id=ctx.family_id,
                user_id=ctx.user_id,
                date_from=date_from,
                date_to=date_to,
                limit=100,
            )
        except Exception:
            return ""

        if not events:
            return ""

        type_counts: dict[str, int] = {}
        for ev in events:
            t = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
            type_counts[t] = type_counts.get(t, 0) + 1

        lines = [f"- {t}: {c}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])]
        return f"Life events ({len(events)} total):\n" + "\n".join(lines)

    async def _collect_upcoming_events(
        self, ctx: SessionContext, today: date
    ) -> str:
        """Collect upcoming calendar events for the next 7 days."""
        try:
            from src.core.models.calendar_cache import CalendarCache

            next_week = today + timedelta(days=7)
            async with async_session() as session:
                result = await session.execute(
                    select(CalendarCache)
                    .where(
                        CalendarCache.family_id == uuid.UUID(ctx.family_id),
                        CalendarCache.start_time >= today,
                        CalendarCache.start_time < next_week,
                    )
                    .order_by(CalendarCache.start_time.asc())
                    .limit(5)
                )
                events = list(result.scalars().all())
        except Exception:
            return ""

        if not events:
            return ""

        lines = []
        for ev in events:
            day = ev.start_time.strftime("%a %b %d") if ev.start_time else ""
            lines.append(f"- {day}: {ev.summary or 'Event'}")
        return f"Upcoming this week ({len(events)}):\n" + "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM synthesis
    # ------------------------------------------------------------------
    async def _synthesize(self, data: dict[str, str], ctx: SessionContext) -> str:
        combined = "\n\n".join(f"[{key}]\n{text}" for key, text in data.items())
        system = self.get_system_prompt(ctx)

        try:
            return await generate_text(
                self.model,
                system,
                [{"role": "user", "content": combined}],
                max_tokens=1024,
            )
        except Exception as e:
            logger.warning("Weekly digest synthesis failed: %s", e)
            # Return raw data as fallback
            return "<b>Your week in review</b>\n\n" + "\n\n".join(data.values())


skill = WeeklyDigestSkill()
