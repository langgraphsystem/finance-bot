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
from src.core.observability import observe

logger = logging.getLogger(__name__)


@observe(name="check_anomalies")
async def check_anomalies(family_id: str) -> list[str]:
    """Detect spending anomalies using z-score > 2.

    Compares today's spending per category against the 30-day daily average.
    Alerts when the ratio exceeds 2.5x (roughly z-score > 2 for typical
    spending distributions).
    """
    alerts: list[str] = []
    today = date.today()

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
                        f"⚠️ Необычно: {category} "
                        f"${float(amount):.2f} "
                        f"(обычно ~${float(avg):.2f}"
                        f"/день, x{ratio:.1f})"
                    )
    return alerts


@observe(name="check_budgets")
async def check_budgets(family_id: str) -> list[str]:
    """Check budget thresholds (80% and 100%).

    Iterates over all active budgets for the family and compares current
    period spending against the budget amount.
    """
    alerts: list[str] = []
    today = date.today()

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
                cat_name = "\u041e\u0431\u0449\u0438\u0439"
                if budget.category_id:
                    cat_result = await session.execute(
                        select(Category.name).where(Category.id == budget.category_id)
                    )
                    cat_name = (
                        cat_result.scalar()
                        or "\u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f"
                    )

                if ratio >= 1.0:
                    alerts.append(
                        f"\U0001f534 \u0411\u044e\u0434\u0436\u0435\u0442 "
                        f"\u00ab{cat_name}\u00bb "
                        f"\u043f\u0440\u0435\u0432\u044b\u0448\u0435\u043d: "
                        f"${float(spent):.2f} / "
                        f"${float(budget.amount):.2f}"
                    )
                elif ratio >= float(budget.alert_at):
                    pct = int(ratio * 100)
                    alerts.append(
                        f"\U0001f7e1 {pct}% "
                        f"\u0431\u044e\u0434\u0436\u0435\u0442\u0430 "
                        f"\u00ab{cat_name}\u00bb "
                        f"\u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u043e:"
                        f" "
                        f"${float(spent):.2f} / "
                        f"${float(budget.amount):.2f}"
                    )
    return alerts


async def collect_alerts(family_id: str) -> list[str]:
    """Collect all alerts for a family.

    Runs anomaly detection and budget checks, combining results.
    Each check is wrapped in its own try/except so a failure in one
    does not prevent the others from running.
    """
    alerts: list[str] = []
    try:
        anomalies = await check_anomalies(family_id)
        alerts.extend(anomalies)
    except Exception as e:
        logger.warning(
            "Anomaly check failed for family %s: %s",
            family_id,
            e,
        )

    try:
        budget_alerts = await check_budgets(family_id)
        alerts.extend(budget_alerts)
    except Exception as e:
        logger.warning(
            "Budget check failed for family %s: %s",
            family_id,
            e,
        )

    return alerts


async def format_notification(alerts: list[str]) -> str:
    """Format alerts into a user-friendly notification message.

    Returns empty string when there are no alerts.
    """
    if not alerts:
        return ""
    header = (
        "\U0001f4ca "
        "\u0424\u0438\u043d\u0430\u043d\u0441\u043e\u0432\u044b\u0435 "
        "\u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f:\n\n"
    )
    return header + "\n".join(alerts)
