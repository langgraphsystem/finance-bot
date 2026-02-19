"""Trigger definitions for the proactivity engine.

Triggers are evaluated WITHOUT LLM. Only when a trigger fires does the engine
call an LLM to generate the notification message.

Two types:
- TimeTrigger: fires at a specific hour in the user's timezone.
- DataTrigger: fires when a condition function returns truthy data.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from src.core.db import async_session
from src.core.models.enums import TaskStatus, TransactionType
from src.core.models.task import Task
from src.core.models.transaction import Transaction

logger = logging.getLogger(__name__)


@dataclass
class TimeTrigger:
    """Fires at a specific hour (user's local time)."""

    name: str
    hour: int
    action: str


@dataclass
class DataTrigger:
    """Fires when check() returns non-empty data."""

    name: str
    action: str

    async def check(self, user_id: str, family_id: str) -> dict[str, Any]:
        """Override in subclasses. Return data dict if triggered, empty dict if not."""
        return {}


class DeadlineWarning(DataTrigger):
    """Tasks due within 4 hours."""

    def __init__(self):
        super().__init__(name="task_deadline", action="deadline_warning")

    async def check(self, user_id: str, family_id: str) -> dict[str, Any]:
        import uuid

        now = datetime.now(UTC)
        horizon = now + timedelta(hours=4)

        async with async_session() as session:
            result = await session.execute(
                select(Task)
                .where(
                    Task.family_id == uuid.UUID(family_id),
                    Task.user_id == uuid.UUID(user_id),
                    Task.status == TaskStatus.pending,
                    Task.due_at.isnot(None),
                    Task.due_at > now,
                    Task.due_at <= horizon,
                )
                .order_by(Task.due_at.asc())
                .limit(5)
            )
            tasks = list(result.scalars().all())

        if not tasks:
            return {}

        return {"tasks": [{"title": t.title, "due_at": t.due_at.isoformat()} for t in tasks]}


class BudgetAlert(DataTrigger):
    """Monthly spending exceeds 80% of budget."""

    def __init__(self):
        super().__init__(name="budget_alert", action="budget_warning")

    async def check(self, user_id: str, family_id: str) -> dict[str, Any]:
        import uuid

        from src.core.models.budget import Budget

        today = date.today()
        month_start = today.replace(day=1)

        async with async_session() as session:
            # Get monthly budget
            budget_result = await session.execute(
                select(Budget).where(
                    Budget.family_id == uuid.UUID(family_id),
                    Budget.period == "monthly",
                )
            )
            budgets = list(budget_result.scalars().all())
            if not budgets:
                return {}

            total_budget = sum(float(b.amount) for b in budgets)
            if total_budget == 0:
                return {}

            # Get monthly spending
            spend_result = await session.execute(
                select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.type == TransactionType.expense,
                    Transaction.date >= month_start,
                )
            )
            total_spent = float(spend_result.scalar() or 0)

        ratio = total_spent / total_budget
        if ratio < 0.8:
            return {}

        return {
            "total_budget": total_budget,
            "total_spent": total_spent,
            "ratio_pct": round(ratio * 100),
        }


class OverdueInvoice(DataTrigger):
    """Recurring payments overdue > 7 days."""

    def __init__(self):
        super().__init__(name="overdue_invoice", action="invoice_reminder")

    async def check(self, user_id: str, family_id: str) -> dict[str, Any]:
        import uuid

        from src.core.models.recurring_payment import RecurringPayment

        threshold = date.today() - timedelta(days=7)

        async with async_session() as session:
            result = await session.execute(
                select(RecurringPayment)
                .where(
                    RecurringPayment.family_id == uuid.UUID(family_id),
                    RecurringPayment.is_active.is_(True),
                    RecurringPayment.next_date < threshold,
                )
                .limit(5)
            )
            overdue = list(result.scalars().all())

        if not overdue:
            return {}

        return {
            "overdue": [
                {"name": r.name, "amount": float(r.amount), "due": r.next_date.isoformat()}
                for r in overdue
            ]
        }


# All data triggers to evaluate
DATA_TRIGGERS: list[DataTrigger] = [
    DeadlineWarning(),
    BudgetAlert(),
    OverdueInvoice(),
]

# Time-based triggers (handled by the scheduler)
TIME_TRIGGERS: list[TimeTrigger] = [
    TimeTrigger(name="morning_brief", hour=7, action="send_morning_brief"),
    TimeTrigger(name="evening_recap", hour=21, action="send_evening_recap"),
]
