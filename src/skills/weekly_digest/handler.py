"""Weekly digest — cross-domain weekly summary."""

import asyncio
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "no_data": (
            "Not enough data for a weekly digest yet. "
            "Keep tracking your expenses, tasks, and life events!"
        ),
    },
    "ru": {
        "no_data": (
            "Недостаточно данных для еженедельного дайджеста. "
            "Продолжайте отслеживать расходы, задачи и события!"
        ),
    },
    "es": {
        "no_data": (
            "Aún no hay suficientes datos para un resumen semanal. "
            "¡Sigue registrando tus gastos, tareas y eventos!"
        ),
    },
}
register_strings("weekly_digest", _STRINGS)

_DEFAULT_SYSTEM_PROMPT = """\
You create a concise "Your week in review" digest.
Sections: Spending, Tasks, Life, Upcoming.
Rules:
- Bullet points, max 12 total.
- Include vs-last-week comparisons if data allows.
- End with one actionable question.
- Use HTML tags for Telegram (<b>, <i>). No Markdown.
- Respond in: {language}."""

# Keep old name as alias so execute() references still work
WEEKLY_DIGEST_SYSTEM_PROMPT = _DEFAULT_SYSTEM_PROMPT


class WeeklyDigestSkill:
    name = "weekly_digest"
    intents = ["weekly_digest"]
    model = "claude-sonnet-4-6"

    @observe(name="weekly_digest")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        today = date.today()
        week_start = today - timedelta(days=7)

        collectors = [
            self._collect_spending(context, week_start, today),
            self._collect_spending_by_category(context, week_start, today),
            self._collect_completed_tasks(context, week_start, today),
            self._collect_pending_tasks(context),
            self._collect_life_events(context, week_start, today),
            self._collect_upcoming_events(context, today),
        ]

        results = await asyncio.gather(*collectors, return_exceptions=True)
        sections = []
        for r in results:
            if isinstance(r, str) and r:
                sections.append(r)
            elif isinstance(r, Exception):
                logger.warning("Weekly digest collector failed: %s", r)

        if not sections:
            return SkillResult(
                response_text=t_cached(
                    _STRINGS, "no_data", context.language, namespace="weekly_digest"
                )
            )

        combined = "\n\n".join(sections)
        prompt = WEEKLY_DIGEST_SYSTEM_PROMPT.format(language=context.language)

        response = await generate_text(
            model=self.model,
            system=prompt,
            messages=[{"role": "user", "content": f"Weekly data:\n{combined}"}],
        )

        return SkillResult(response_text=response)

    async def _collect_spending(
        self, context: SessionContext, week_start: date, today: date
    ) -> str:
        from sqlalchemy import text

        from src.core.db import async_session

        try:
            async with async_session() as session:
                result = await asyncio.wait_for(
                    session.execute(
                        text("""
                            SELECT COALESCE(SUM(amount), 0) as total,
                                   COUNT(*) as count
                            FROM transactions
                            WHERE family_id = :fid
                              AND type = 'expense'
                              AND date >= :start AND date <= :end
                        """),
                        {"fid": context.family_id, "start": week_start, "end": today},
                    ),
                    timeout=4.0,
                )
                row = result.first()
                if not row or row.count == 0:
                    return ""
                # Previous week for comparison
                prev_start = week_start - timedelta(days=7)
                prev_result = await asyncio.wait_for(
                    session.execute(
                        text("""
                            SELECT COALESCE(SUM(amount), 0) as total
                            FROM transactions
                            WHERE family_id = :fid
                              AND type = 'expense'
                              AND date >= :start AND date < :end
                        """),
                        {
                            "fid": context.family_id,
                            "start": prev_start,
                            "end": week_start,
                        },
                    ),
                    timeout=4.0,
                )
                prev_row = prev_result.first()
                prev_total = float(prev_row.total) if prev_row else 0
                total = float(row.total)
                section = (
                    f"SPENDING: {context.currency} {total:.0f} this week ({row.count} transactions)"
                )
                if prev_total > 0:
                    change = ((total - prev_total) / prev_total) * 100
                    section += f" | vs last week: {change:+.0f}%"
                return section
        except Exception as e:
            logger.warning("Failed to collect spending: %s", e)
            return ""

    async def _collect_spending_by_category(
        self, context: SessionContext, week_start: date, today: date
    ) -> str:
        from sqlalchemy import text

        from src.core.db import async_session

        try:
            async with async_session() as session:
                result = await asyncio.wait_for(
                    session.execute(
                        text("""
                            SELECT category, COALESCE(SUM(amount), 0) as total
                            FROM transactions
                            WHERE family_id = :fid
                              AND type = 'expense'
                              AND date >= :start AND date <= :end
                            GROUP BY category
                            ORDER BY total DESC
                            LIMIT 5
                        """),
                        {"fid": context.family_id, "start": week_start, "end": today},
                    ),
                    timeout=4.0,
                )
                rows = result.all()
                if not rows:
                    return ""
                lines = [f"  - {r.category}: {context.currency} {float(r.total):.0f}" for r in rows]
                return "TOP CATEGORIES:\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to collect category spending: %s", e)
            return ""

    async def _collect_completed_tasks(
        self, context: SessionContext, week_start: date, today: date
    ) -> str:
        from sqlalchemy import text

        from src.core.db import async_session

        try:
            async with async_session() as session:
                result = await asyncio.wait_for(
                    session.execute(
                        text("""
                            SELECT COUNT(*) as count
                            FROM tasks
                            WHERE family_id = :fid
                              AND status = 'done'
                              AND updated_at >= :start
                        """),
                        {"fid": context.family_id, "start": week_start},
                    ),
                    timeout=4.0,
                )
                row = result.first()
                count = row.count if row else 0
                if count == 0:
                    return ""
                return f"COMPLETED TASKS: {count} tasks done this week"
        except Exception as e:
            logger.warning("Failed to collect completed tasks: %s", e)
            return ""

    async def _collect_pending_tasks(self, context: SessionContext) -> str:
        from sqlalchemy import text

        from src.core.db import async_session

        try:
            async with async_session() as session:
                result = await asyncio.wait_for(
                    session.execute(
                        text("""
                            SELECT title, deadline
                            FROM tasks
                            WHERE family_id = :fid
                              AND status != 'done'
                            ORDER BY deadline ASC NULLS LAST
                            LIMIT 5
                        """),
                        {"fid": context.family_id},
                    ),
                    timeout=4.0,
                )
                rows = result.all()
                if not rows:
                    return ""
                lines = []
                for r in rows:
                    line = f"  - {r.title}"
                    if r.deadline:
                        line += f" (due: {r.deadline})"
                    lines.append(line)
                return "PENDING TASKS:\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to collect pending tasks: %s", e)
            return ""

    async def _collect_life_events(
        self, context: SessionContext, week_start: date, today: date
    ) -> str:
        from sqlalchemy import text

        from src.core.db import async_session

        try:
            async with async_session() as session:
                result = await asyncio.wait_for(
                    session.execute(
                        text("""
                            SELECT type, COUNT(*) as count
                            FROM life_events
                            WHERE family_id = :fid
                              AND user_id = :uid
                              AND date >= :start AND date <= :end
                            GROUP BY type
                        """),
                        {
                            "fid": context.family_id,
                            "uid": context.user_id,
                            "start": week_start,
                            "end": today,
                        },
                    ),
                    timeout=4.0,
                )
                rows = result.all()
                if not rows:
                    return ""
                lines = [f"  - {r.type}: {r.count}" for r in rows]
                return "LIFE EVENTS:\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to collect life events: %s", e)
            return ""

    async def _collect_upcoming_events(self, context: SessionContext, today: date) -> str:
        from sqlalchemy import text

        from src.core.db import async_session

        next_week = today + timedelta(days=7)
        try:
            async with async_session() as session:
                result = await asyncio.wait_for(
                    session.execute(
                        text("""
                            SELECT summary, start_time
                            FROM calendar_cache
                            WHERE family_id = :fid
                              AND start_time >= :start AND start_time < :end
                            ORDER BY start_time
                            LIMIT 5
                        """),
                        {"fid": context.family_id, "start": today, "end": next_week},
                    ),
                    timeout=4.0,
                )
                rows = result.all()
                if not rows:
                    return ""
                lines = [f"  - {r.summary} ({r.start_time})" for r in rows]
                return "UPCOMING (next 7 days):\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to collect upcoming events: %s", e)
            return ""

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language)


skill = WeeklyDigestSkill()
