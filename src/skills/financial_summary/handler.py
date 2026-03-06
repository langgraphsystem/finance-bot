"""Financial summary skill — deep spending/income analysis by category with trends.

Bookkeeper specialist: provides weekly/monthly breakdowns, category analysis,
top merchants, and comparisons with previous periods.
"""

import logging
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from src.core.access import apply_scope_filter
from src.core.charts import create_pie_chart
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import generate_text
from src.core.models.category import Category
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "no_account": "Set up your account first to get financial summaries.",
        "no_data": "No transactions found for {period}. Start recording expenses to get summaries.",
        "data_summary": "{count} transactions for {period} ({currency} {total})",
        "period_this_week": "this week",
        "period_last_week": "last week",
        "period_last_month": "last month",
        "period_this_year": "this year",
        "period_this_month": "this month",
    },
    "ru": {
        "no_account": "Сначала настройте аккаунт для получения финансовых сводок.",
        "no_data": "За {period} транзакций не найдено. Начните записывать расходы.",
        "data_summary": "{count} операций за {period} ({currency} {total})",
        "period_this_week": "эту неделю",
        "period_last_week": "прошлую неделю",
        "period_last_month": "прошлый месяц",
        "period_this_year": "этот год",
        "period_this_month": "этот месяц",
    },
    "es": {
        "no_account": "Configure su cuenta primero para obtener resúmenes financieros.",
        "no_data": "No se encontraron transacciones para {period}. Comience a registrar gastos.",
        "data_summary": "{count} transacciones para {period} ({currency} {total})",
        "period_this_week": "esta semana",
        "period_last_week": "la semana pasada",
        "period_last_month": "el mes pasado",
        "period_this_year": "este año",
        "period_this_month": "este mes",
    },
}
register_strings("financial_summary", _STRINGS)

SUMMARY_SYSTEM_PROMPT = """\
You are a bookkeeper assistant that produces clear financial summaries.
You receive READY data from SQL. NEVER calculate yourself.
Format a concise, scannable summary using HTML tags for Telegram.
Include: category breakdown, top merchants, period comparison, actionable insight.
Lead with the total, then break down by category.
Max 8 lines. Use <b>bold</b> for key numbers.
Respond in: {language}."""

_PERIOD_KEYS = {
    "week": "period_this_week",
    "prev_week": "period_last_week",
    "prev_month": "period_last_month",
    "year": "period_this_year",
    "month": "period_this_month",
}


def _resolve_period(intent_data: dict[str, Any], lang: str = "en") -> tuple[date, date, str]:
    """Resolve period from intent data."""
    today = date.today()
    period = intent_data.get("period") or "month"
    label = t_cached(_STRINGS, _PERIOD_KEYS.get(period, "period_this_month"), lang,
                     namespace="financial_summary")

    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1), label

    if period == "prev_week":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
        return start, end, label

    if period == "prev_month":
        first = today.replace(day=1)
        if today.month == 1:
            start = today.replace(year=today.year - 1, month=12, day=1)
        else:
            start = today.replace(month=today.month - 1, day=1)
        return start, first, label

    if period == "year":
        start = today.replace(month=1, day=1)
        return start, today + timedelta(days=1), label

    # Default: current month
    start = today.replace(day=1)
    return start, today + timedelta(days=1), label


class FinancialSummarySkill:
    name = "financial_summary"
    intents = ["financial_summary"]
    model = "claude-sonnet-4-6"

    def get_system_prompt(self, context: SessionContext) -> str:
        return SUMMARY_SYSTEM_PROMPT.format(language=context.language or "en")

    @observe(name="skill_financial_summary")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        family_id = context.family_id
        lang = context.language or "en"
        if not family_id:
            return SkillResult(
                response_text=t_cached(
                    _STRINGS, "no_account", lang, namespace="financial_summary"
                )
            )

        # Ask for period if request is ambiguous
        from src.skills._clarification import maybe_ask_period

        clarify = await maybe_ask_period(
            "financial_summary", intent_data, message.text or "",
            context.user_id, lang,
        )
        if clarify:
            return clarify

        start_date, end_date, period_label = _resolve_period(intent_data, lang)

        # Fetch category breakdown
        categories = await self._get_category_breakdown(
            family_id, start_date, end_date, role=context.role
        )
        # Fetch top merchants
        merchants = await self._get_top_merchants(
            family_id, start_date, end_date, role=context.role, limit=5
        )
        # Fetch income total
        income_total = await self._get_income_total(
            family_id, start_date, end_date, role=context.role
        )
        # Fetch previous period for comparison
        period_days = (end_date - start_date).days
        prev_start = start_date - timedelta(days=period_days)
        prev_categories = await self._get_category_breakdown(
            family_id, prev_start, start_date, role=context.role
        )

        if not categories and not income_total:
            return SkillResult(
                response_text=t_cached(
                    _STRINGS, "no_data", lang, namespace="financial_summary",
                    period=period_label,
                )
            )

        # Build data context for LLM
        expense_total = sum(c["amount"] for c in categories)
        prev_total = sum(c["amount"] for c in prev_categories)
        tx_count = sum(c.get("count", 0) for c in categories)

        data_text = self._format_data(
            categories, merchants, income_total, expense_total,
            prev_total, period_label, context.currency,
        )

        # Generate chart
        chart_url = None
        if len(categories) >= 2:
            labels = [c["category"] for c in categories[:8]]
            values = [float(c["amount"]) for c in categories[:8]]
            chart_url = create_pie_chart(
                labels, values, f"Expenses — {period_label}"
            )

        # LLM generates natural response
        model = intent_data.get("_model", self.model)
        response = await generate_text(
            model=model,
            system=SUMMARY_SYSTEM_PROMPT.format(language=lang),
            prompt=f"{message.text}\n\n--- DATA ---\n{data_text}",
            max_tokens=2048,
        )

        # Prepend data summary so user sees what data was used
        summary_line = t_cached(
            _STRINGS, "data_summary", lang, namespace="financial_summary",
            count=tx_count,
            period=period_label,
            currency=context.currency,
            total=f"{expense_total + income_total:.2f}",
        )
        response = f"<i>{summary_line}</i>\n\n{response}"

        return SkillResult(response_text=response, chart_url=chart_url)

    @staticmethod
    async def _get_category_breakdown(
        family_id: str, start: date, end: date, role: str = "owner",
    ) -> list[dict[str, Any]]:
        """Get expense totals grouped by category."""
        async with async_session() as session:
            stmt = (
                select(
                    Category.name.label("category"),
                    func.sum(Transaction.amount).label("total"),
                    func.count(Transaction.id).label("count"),
                )
                .join(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.type == TransactionType.expense,
                    Transaction.date >= start,
                    Transaction.date < end,
                )
                .group_by(Category.name)
                .order_by(func.sum(Transaction.amount).desc())
            )
            rows = (await session.execute(apply_scope_filter(stmt, Transaction, role))).all()
            return [
                {
                    "category": r.category,
                    "amount": float(r.total or 0),
                    "count": r.count,
                }
                for r in rows
            ]

    @staticmethod
    async def _get_top_merchants(
        family_id: str, start: date, end: date, role: str = "owner", limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get top merchants by spend."""
        async with async_session() as session:
            stmt = (
                select(
                    Transaction.merchant,
                    func.sum(Transaction.amount).label("total"),
                    func.count(Transaction.id).label("count"),
                )
                .where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.type == TransactionType.expense,
                    Transaction.date >= start,
                    Transaction.date < end,
                    Transaction.merchant.isnot(None),
                )
                .group_by(Transaction.merchant)
                .order_by(func.sum(Transaction.amount).desc())
                .limit(limit)
            )
            rows = (await session.execute(apply_scope_filter(stmt, Transaction, role))).all()
            return [
                {"merchant": r.merchant, "amount": float(r.total or 0), "count": r.count}
                for r in rows
            ]

    @staticmethod
    async def _get_income_total(
        family_id: str, start: date, end: date, role: str = "owner"
    ) -> float:
        """Get total income for the period."""
        async with async_session() as session:
            stmt = select(func.sum(Transaction.amount)).where(
                Transaction.family_id == uuid.UUID(family_id),
                Transaction.type == TransactionType.income,
                Transaction.date >= start,
                Transaction.date < end,
            )
            result = await session.scalar(apply_scope_filter(stmt, Transaction, role))
            return float(result or 0)

    @staticmethod
    def _format_data(
        categories: list[dict],
        merchants: list[dict],
        income: float,
        expense_total: float,
        prev_total: float,
        period_label: str,
        currency: str,
    ) -> str:
        """Format data for LLM context."""
        lines = [f"Period: {period_label}", f"Currency: {currency}"]
        lines.append(f"Total expenses: {expense_total:.2f}")
        lines.append(f"Total income: {income:.2f}")
        lines.append(f"Net: {income - expense_total:.2f}")

        if prev_total > 0:
            pct = ((expense_total - prev_total) / prev_total) * 100
            direction = "up" if pct > 0 else "down"
            lines.append(
                f"Compared to previous period: {direction} {abs(pct):.0f}% "
                f"(prev: {prev_total:.2f})"
            )

        if categories:
            lines.append("\nCategory breakdown:")
            for c in categories[:10]:
                pct = (c["amount"] / expense_total * 100) if expense_total else 0
                lines.append(
                    f"  {c['category']}: {c['amount']:.2f} ({pct:.0f}%, {c['count']} txns)"
                )

        if merchants:
            lines.append("\nTop merchants:")
            for m in merchants:
                lines.append(f"  {m['merchant']}: {m['amount']:.2f} ({m['count']} txns)")

        return "\n".join(lines)


skill = FinancialSummarySkill()
