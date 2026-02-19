"""Brief orchestrator graph nodes — cross-domain data collectors + synthesizer.

Each collector node queries a single domain (calendar, tasks, finance, email)
and writes its result into the shared state. The synthesizer assembles
all collected data into a single LLM-generated message.

All collectors handle errors gracefully: on failure they write "" so the
synthesizer simply skips that section.
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from src.core.connectors import connector_registry
from src.core.db import async_session
from src.core.google_auth import parse_email_headers
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.models.enums import (
    TaskPriority,
    TaskStatus,
    TransactionType,
)
from src.core.models.recurring_payment import RecurringPayment
from src.core.models.task import Task
from src.core.models.transaction import Transaction
from src.orchestrators.brief.state import BriefState

logger = logging.getLogger(__name__)

COLLECTOR_TIMEOUT_S = 3.0

# ---------------------------------------------------------------------------
# Collector nodes
# ---------------------------------------------------------------------------


async def collect_calendar(state: BriefState) -> dict[str, Any]:
    """Fetch today's events from Google Calendar."""
    user_id = state.get("user_id", "")
    try:
        google = connector_registry.get("google")
        if not google or not await google.is_connected(user_id):
            return {"calendar_data": ""}

        client = await google.get_client(user_id)
        if not client:
            return {"calendar_data": ""}

        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        events = await client.list_events(today_start, today_end)
        if not events:
            return {"calendar_data": ""}

        lines = []
        for e in events[:8]:
            time_str = e.get("start", {}).get(
                "dateTime", e.get("start", {}).get("date", "?")
            )
            summary = e.get("summary", "(no title)")
            lines.append(f"- {time_str}: {summary}")
        return {"calendar_data": "Today's calendar:\n" + "\n".join(lines)}
    except Exception as e:
        logger.warning("collect_calendar failed: %s", e)
        return {"calendar_data": ""}


async def collect_tasks(state: BriefState) -> dict[str, Any]:
    """Fetch open or completed tasks from DB."""
    intent = state.get("intent", "morning_brief")
    family_id = state.get("family_id", "")
    user_id = state.get("user_id", "")

    try:
        if intent == "evening_recap":
            return await _collect_completed_tasks(user_id, family_id)
        return await _collect_open_tasks(user_id, family_id)
    except Exception as e:
        logger.warning("collect_tasks failed: %s", e)
        return {"tasks_data": ""}


async def _collect_open_tasks(user_id: str, family_id: str) -> dict[str, Any]:
    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .where(
                Task.family_id == uuid.UUID(family_id),
                Task.user_id == uuid.UUID(user_id),
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]),
            )
            .order_by(Task.due_at.asc().nulls_last())
            .limit(6)
        )
        tasks = list(result.scalars().all())

    if not tasks:
        return {"tasks_data": ""}

    lines = []
    for t in tasks:
        priority = ""
        if t.priority in (TaskPriority.urgent, TaskPriority.high):
            priority = f"[{t.priority.value}] "
        due = ""
        if t.due_at:
            due = f" — due {t.due_at.strftime('%b %d')}"
        lines.append(f"- {priority}{t.title}{due}")
    return {"tasks_data": f"Open tasks ({len(tasks)}):\n" + "\n".join(lines)}


async def _collect_completed_tasks(
    user_id: str, family_id: str
) -> dict[str, Any]:
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .where(
                Task.family_id == uuid.UUID(family_id),
                Task.user_id == uuid.UUID(user_id),
                Task.status == TaskStatus.done,
                Task.completed_at >= today,
            )
            .limit(10)
        )
        tasks = list(result.scalars().all())

    if not tasks:
        return {"tasks_data": ""}

    lines = [f"- {t.title}" for t in tasks]
    return {
        "tasks_data": f"Completed today ({len(tasks)}):\n" + "\n".join(lines)
    }


async def collect_finance(state: BriefState) -> dict[str, Any]:
    """Fetch spending data from DB."""
    family_id = state.get("family_id", "")
    intent = state.get("intent", "morning_brief")

    try:
        if intent == "evening_recap":
            return await _collect_today_spending(family_id)
        return await _collect_finance_summary(family_id)
    except Exception as e:
        logger.warning("collect_finance failed: %s", e)
        return {"finance_data": ""}


async def _collect_finance_summary(family_id: str) -> dict[str, Any]:
    today = date.today()
    yesterday = today - timedelta(days=1)

    async with async_session() as session:
        result = await session.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= yesterday,
                Transaction.date < today,
                Transaction.type == TransactionType.expense,
            )
        )
        yesterday_expense = float(result.scalar() or 0)

        result2 = await session.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= today.replace(day=1),
                Transaction.type == TransactionType.expense,
            )
        )
        month_expense = float(result2.scalar() or 0)

    if yesterday_expense == 0 and month_expense == 0:
        return {"finance_data": ""}

    parts = []
    if yesterday_expense > 0:
        parts.append(f"Yesterday: ${yesterday_expense:.2f} spent")
    parts.append(f"This month: ${month_expense:.2f} total")
    return {"finance_data": "Money:\n" + "\n".join(f"- {p}" for p in parts)}


async def _collect_today_spending(family_id: str) -> dict[str, Any]:
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(
                func.sum(Transaction.amount), func.count(Transaction.id)
            ).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= today,
                Transaction.type == TransactionType.expense,
            )
        )
        row = result.one_or_none()

    if not row or not row[0]:
        return {"finance_data": ""}

    total = float(row[0])
    count = row[1]
    return {
        "finance_data": (
            f"Spending today:\n- ${total:.2f} across {count} transactions"
        )
    }


async def collect_email(state: BriefState) -> dict[str, Any]:
    """Fetch unread important emails from Gmail."""
    user_id = state.get("user_id", "")
    try:
        google = connector_registry.get("google")
        if not google or not await google.is_connected(user_id):
            return {"email_data": ""}

        client = await google.get_client(user_id)
        if not client:
            return {"email_data": ""}

        messages = await client.list_messages(
            "is:unread is:important", max_results=5
        )
        if not messages:
            return {"email_data": ""}

        parsed = [parse_email_headers(m) for m in messages]
        lines = [f"- {e['from']}: {e['subject']}" for e in parsed[:5]]
        return {
            "email_data": (
                f"Unread emails ({len(parsed)}):\n" + "\n".join(lines)
            )
        }
    except Exception as e:
        logger.warning("collect_email failed: %s", e)
        return {"email_data": ""}


async def collect_outstanding(state: BriefState) -> dict[str, Any]:
    """Fetch overdue recurring payments."""
    family_id = state.get("family_id", "")
    try:
        today = date.today()
        async with async_session() as session:
            result = await session.execute(
                select(RecurringPayment)
                .where(
                    RecurringPayment.family_id == uuid.UUID(family_id),
                    RecurringPayment.next_date < today,
                    RecurringPayment.is_active.is_(True),
                )
                .limit(5)
            )
            overdue = list(result.scalars().all())

        if not overdue:
            return {"outstanding_data": ""}

        lines = [f"- {r.name}: ${float(r.amount):.2f}" for r in overdue]
        return {
            "outstanding_data": (
                f"Overdue ({len(overdue)}):\n" + "\n".join(lines)
            )
        }
    except Exception as e:
        logger.warning("collect_outstanding failed: %s", e)
        return {"outstanding_data": ""}


# ---------------------------------------------------------------------------
# Synthesizer node
# ---------------------------------------------------------------------------

MORNING_SYSTEM = """\
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

EVENING_SYSTEM = """\
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


async def synthesize(state: BriefState) -> dict[str, Any]:
    """Combine all collected data and generate the final message via LLM."""
    intent = state.get("intent", "morning_brief")
    language = state.get("language", "en")

    section_map = {
        "schedule": state.get("calendar_data", ""),
        "jobs_today": state.get("calendar_data", ""),
        "tasks": state.get("tasks_data", ""),
        "completed_tasks": state.get("tasks_data", ""),
        "completed_jobs": state.get("tasks_data", ""),
        "money_summary": state.get("finance_data", ""),
        "spending_total": state.get("finance_data", ""),
        "email_highlights": state.get("email_data", ""),
        "outstanding": state.get("outstanding_data", ""),
        "invoices_sent": "",
    }

    active_sections = state.get("active_sections", [])
    data = {k: section_map.get(k, "") for k in active_sections}
    data = {k: v for k, v in data.items() if v}

    if not data:
        if intent == "evening_recap":
            return {"response_text": "Not much to recap today. Rest up!"}
        return {
            "response_text": (
                "Couldn't load data for your morning brief. Try again later."
            )
        }

    combined = "\n\n".join(f"[{key}]\n{text}" for key, text in data.items())

    if intent == "evening_recap":
        system = EVENING_SYSTEM.format(language=language)
    else:
        system = MORNING_SYSTEM.format(language=language)

    model = "claude-sonnet-4-6"
    client = anthropic_client()
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": combined}],
    )
    try:
        response = await client.messages.create(
            model=model, max_tokens=1024, **prompt_data
        )
        return {"response_text": response.content[0].text}
    except Exception as e:
        logger.warning("Brief synthesis failed: %s", e)
        if intent == "evening_recap":
            return {"response_text": "Couldn't prepare your evening recap."}
        return {"response_text": "Couldn't prepare your morning brief."}
