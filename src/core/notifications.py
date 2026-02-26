"""Smart notification system -- anomaly detection, budget alerts, trends."""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from src.core.db import async_session
from src.core.models.budget import Budget
from src.core.models.category import Category
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.notifications_pkg.templates import get_financial_text
from src.core.observability import observe

logger = logging.getLogger(__name__)


@observe(name="check_anomalies")
async def check_anomalies(family_id: str, language: str = "en") -> list[str]:
    """Detect spending anomalies using z-score > 2.

    Compares today's spending per category against the 30-day daily average.
    Alerts when the ratio exceeds 2.5x (roughly z-score > 2 for typical
    spending distributions).
    """
    alerts: list[str] = []
    today = date.today()
    t = get_financial_text(language)

    async with async_session() as session:
        # Get today's spending by category
        today_result = await session.execute(
            select(
                Category.name,
                func.sum(Transaction.amount).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date == today,
                Transaction.type == TransactionType.expense,
            )
            .group_by(Category.name)
        )
        today_spending = {row[0]: row[1] for row in today_result.all()}

        # Get 30-day daily average by category
        start_30d = today - timedelta(days=30)
        avg_result = await session.execute(
            select(
                Category.name,
                (func.sum(Transaction.amount) / 30).label("daily_avg"),
            )
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start_30d,
                Transaction.date < today,
                Transaction.type == TransactionType.expense,
            )
            .group_by(Category.name)
        )
        avg_spending = {row[0]: row[1] for row in avg_result.all()}

        for category, amount in today_spending.items():
            avg = avg_spending.get(category, Decimal("0"))
            if avg > 0:
                ratio = float(amount) / float(avg)
                if ratio > 2.5:
                    alerts.append(
                        t["anomaly"].format(
                            category=category,
                            amount=float(amount),
                            avg=float(avg),
                            ratio=ratio,
                        )
                    )
    return alerts


@observe(name="check_budgets")
async def check_budgets(family_id: str, language: str = "en") -> list[str]:
    """Check budget thresholds (80% and 100%).

    Iterates over all active budgets for the family and compares current
    period spending against the budget amount.
    """
    alerts: list[str] = []
    today = date.today()
    t = get_financial_text(language)

    async with async_session() as session:
        # Get active budgets
        budget_result = await session.execute(
            select(Budget).where(
                Budget.family_id == uuid.UUID(family_id),
                Budget.is_active == True,  # noqa: E712
            )
        )
        budgets = budget_result.scalars().all()

        for budget in budgets:
            # Determine period start
            if budget.period.value == "weekly":
                period_start = today - timedelta(days=today.weekday())
            else:  # monthly
                period_start = today.replace(day=1)

            # Get spending for this budget's category in the period
            query = select(
                func.sum(Transaction.amount),
            ).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= period_start,
                Transaction.type == TransactionType.expense,
            )
            if budget.category_id:
                query = query.where(
                    Transaction.category_id == budget.category_id,
                )

            spent_result = await session.execute(query)
            spent = spent_result.scalar() or Decimal("0")

            if budget.amount > 0:
                ratio = float(spent) / float(budget.amount)
                # Get category name
                cat_name = t["total"]
                if budget.category_id:
                    cat_result = await session.execute(
                        select(Category.name).where(Category.id == budget.category_id)
                    )
                    cat_name = cat_result.scalar() or t["category_fallback"]

                if ratio >= 1.0:
                    alerts.append(
                        t["budget_exceeded"].format(
                            category=cat_name,
                            spent=float(spent),
                            budget=float(budget.amount),
                        )
                    )
                elif ratio >= float(budget.alert_at):
                    pct = int(ratio * 100)
                    alerts.append(
                        t["budget_warning"].format(
                            pct=pct,
                            category=cat_name,
                            spent=float(spent),
                            budget=float(budget.amount),
                        )
                    )
    return alerts


async def collect_alerts(family_id: str, language: str = "en") -> list[str]:
    """Collect all alerts for a family.

    Runs anomaly detection and budget checks, combining results.
    Each check is wrapped in its own try/except so a failure in one
    does not prevent the others from running.
    """
    alerts: list[str] = []
    try:
        anomalies = await check_anomalies(family_id, language=language)
        alerts.extend(anomalies)
    except Exception as e:
        logger.warning(
            "Anomaly check failed for family %s: %s",
            family_id,
            e,
        )

    try:
        budget_alerts = await check_budgets(family_id, language=language)
        alerts.extend(budget_alerts)
    except Exception as e:
        logger.warning(
            "Budget check failed for family %s: %s",
            family_id,
            e,
        )

    return alerts


async def format_notification(alerts: list[str], language: str = "en") -> str:
    """Format alerts into a user-friendly notification message.

    Returns empty string when there are no alerts.
    """
    if not alerts:
        return ""
    t = get_financial_text(language)
    return t["header"] + "\n".join(alerts)
