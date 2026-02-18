"""Pydantic AI graph workflow agent for complex financial queries."""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from src.core.db import async_session
from src.core.models.budget import Budget
from src.core.models.category import Category
from src.core.models.enums import BudgetPeriod, TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe

logger = logging.getLogger(__name__)


class FinancialInsight(BaseModel):
    """Structured response from the graph agent."""

    summary: str = Field(description="Natural language summary in Russian")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Key financial metrics")
    recommendations: list[str] = Field(
        default_factory=list, description="Actionable recommendations"
    )
    chart_data: dict[str, Any] | None = Field(None, description="Data for chart rendering")


# --- Tool functions the agent can call ---


async def get_monthly_spending(family_id: str, year: int, month: int) -> dict:
    """Get total spending by category for a specific month."""
    from sqlalchemy import func, select

    start = date(year, month, 1)
    end = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)

    async with async_session() as session:
        result = await session.execute(
            select(Category.name, func.sum(Transaction.amount).label("total"))
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start,
                Transaction.date < end,
                Transaction.type == TransactionType.expense,
            )
            .group_by(Category.name)
            .order_by(func.sum(Transaction.amount).desc())
        )
        categories = {r[0]: float(r[1]) for r in result.all()}

        # Total income
        inc = await session.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= start,
                Transaction.date < end,
                Transaction.type == TransactionType.income,
            )
        )
        total_income = float(inc.scalar() or 0)

    return {
        "year": year,
        "month": month,
        "total_expense": sum(categories.values()),
        "total_income": total_income,
        "by_category": categories,
    }


async def get_budget_status(family_id: str) -> list[dict]:
    """Get all active budgets with current spending."""
    from sqlalchemy import func, select

    today = date.today()

    async with async_session() as session:
        budgets = await session.execute(
            select(Budget).where(
                Budget.family_id == uuid.UUID(family_id),
                Budget.is_active == True,  # noqa: E712
            )
        )

        results = []
        for b in budgets.scalars():
            # Period start
            if b.period == BudgetPeriod.weekly:
                period_start = today - timedelta(days=today.weekday())
            else:
                period_start = today.replace(day=1)

            # Current spending
            query = select(func.sum(Transaction.amount)).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.date >= period_start,
                Transaction.type == TransactionType.expense,
            )
            if b.category_id:
                query = query.where(Transaction.category_id == b.category_id)

            spent = (await session.execute(query)).scalar() or Decimal("0")

            # Category name
            cat_name = "Общий"
            if b.category_id:
                cat = await session.execute(
                    select(Category.name).where(Category.id == b.category_id)
                )
                cat_name = cat.scalar() or "Категория"

            results.append(
                {
                    "category": cat_name,
                    "limit": float(b.amount),
                    "spent": float(spent),
                    "percent": float(spent / b.amount * 100) if b.amount > 0 else 0,
                    "period": b.period.value,
                }
            )

    return results


async def get_spending_trend(family_id: str, months: int = 3) -> list[dict]:
    """Get spending totals for the last N months."""
    today = date.today()
    results = []

    for i in range(months):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1

        data = await get_monthly_spending(family_id, year, month)
        results.append(data)

    return list(reversed(results))


@observe(name="graph_agent_query")
async def run_complex_query(
    query: str,
    family_id: str,
) -> FinancialInsight:
    """Run a complex financial query using Pydantic AI agent with tools.

    Falls back to a simple analysis if pydantic-ai is not available.
    """
    try:
        from pydantic_ai import Agent

        agent = Agent(
            "anthropic:claude-sonnet-4-6",
            result_type=FinancialInsight,
            system_prompt=(
                "Ты — финансовый аналитик. Используй доступные инструменты "
                "для получения данных и дай подробный анализ на русском языке. "
                "Всегда используй реальные данные из инструментов, не выдумывай числа."
            ),
        )

        # Register tools
        @agent.tool
        async def monthly_spending(ctx, year: int, month: int) -> dict:
            """Get spending by category for a specific month."""
            return await get_monthly_spending(family_id, year, month)

        @agent.tool
        async def budget_status(ctx) -> list[dict]:
            """Get current budget utilization."""
            return await get_budget_status(family_id)

        @agent.tool
        async def spending_trend(ctx, months: int = 3) -> list[dict]:
            """Get spending trend for last N months."""
            return await get_spending_trend(family_id, months)

        result = await agent.run(query)
        return result.data

    except ImportError:
        logger.warning("pydantic-ai not available, using fallback analysis")
        return await _fallback_analysis(query, family_id)
    except Exception as e:
        logger.error("Graph agent failed: %s", e)
        return await _fallback_analysis(query, family_id)


async def _fallback_analysis(query: str, family_id: str) -> FinancialInsight:
    """Fallback analysis without Pydantic AI — direct tool calls."""
    today = date.today()

    spending = await get_monthly_spending(family_id, today.year, today.month)
    budgets = await get_budget_status(family_id)
    trend = await get_spending_trend(family_id, 3)

    total = spending["total_expense"]
    income = spending["total_income"]
    top_cats = sorted(spending["by_category"].items(), key=lambda x: x[1], reverse=True)[:3]

    summary_parts = [f"Расходы за текущий месяц: ${total:.2f}"]
    if income > 0:
        summary_parts.append(f"Доходы: ${income:.2f}, баланс: ${income - total:.2f}")
    if top_cats:
        summary_parts.append("Топ категории: " + ", ".join(f"{c} (${v:.2f})" for c, v in top_cats))

    recommendations = []
    for b in budgets:
        if b["percent"] >= 100:
            recommendations.append(
                f"Бюджет \u00ab{b['category']}\u00bb превышен ({b['percent']:.0f}%)"
            )
        elif b["percent"] >= 80:
            recommendations.append(
                f"Бюджет \u00ab{b['category']}\u00bb на {b['percent']:.0f}% — будьте внимательны"
            )

    return FinancialInsight(
        summary=". ".join(summary_parts),
        metrics={
            "total_expense": total,
            "total_income": income,
            "balance": income - total,
            "budget_utilization": budgets,
        },
        recommendations=recommendations,
        chart_data={
            "trend": [{"month": t["month"], "total": t["total_expense"]} for t in trend],
            "categories": spending["by_category"],
        },
    )
