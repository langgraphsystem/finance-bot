"""Cash flow forecast skill — predict future income and expenses.

Cash flow specialist: analyzes historical transaction patterns, recurring payments,
and trends to forecast cash flow for the next 30/60/90 days.
"""

import logging
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import generate_text
from src.core.models.enums import TransactionType
from src.core.models.recurring_payment import RecurringPayment
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t_cached
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

FORECAST_SYSTEM_PROMPT = """\
You are a cash flow forecasting assistant.
You receive READY data from SQL: historical averages, trends, and recurring payments.
NEVER calculate yourself — use the provided numbers.
Provide a clear, actionable forecast using HTML tags for Telegram.
Structure: current balance trend → recurring obligations → forecast → recommendation.
Use <b>bold</b> for key amounts. Max 8 lines.
If data is insufficient (<14 days), say so clearly.
Respond in: {language}."""

MIN_HISTORY_DAYS = 14

_STRINGS = {
    "en": {
        "no_account": "Set up your account first to get forecasts.",
        "not_enough_data": (
            "I need at least {min_days} days of data to forecast. "
            "You have {days_have} days so far. Keep tracking and check back soon."
        ),
        "data_summary": "{days} days of data, forecasting {horizon} days ({currency})",
    },
    "ru": {
        "no_account": "Сначала настройте аккаунт для получения прогнозов.",
        "not_enough_data": (
            "Для прогноза нужно минимум {min_days} дней данных. "
            "У вас пока {days_have} дней. Продолжайте записывать и проверьте позже."
        ),
        "data_summary": "{days} дн. данных, прогноз на {horizon} дн. ({currency})",
    },
    "es": {
        "no_account": "Configure su cuenta primero para obtener pronósticos.",
        "not_enough_data": (
            "Necesito al menos {min_days} días de datos para pronosticar. "
            "Tienes {days_have} días hasta ahora. Sigue registrando y vuelve pronto."
        ),
        "data_summary": "{days} días de datos, pronóstico de {horizon} días ({currency})",
    },
}
register_strings("cash_flow_forecast", _STRINGS)


class CashFlowForecastSkill:
    name = "cash_flow_forecast"
    intents = ["cash_flow_forecast"]
    model = "claude-sonnet-4-6"

    def get_system_prompt(self, context: SessionContext) -> str:
        return FORECAST_SYSTEM_PROMPT.format(language=context.language or "en")

    @observe(name="skill_cash_flow_forecast")
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
                    _STRINGS, "no_account", lang, namespace="cash_flow_forecast"
                )
            )

        today = date.today()

        # Check data sufficiency
        first_tx_date = await self._get_first_transaction_date(family_id)
        if not first_tx_date or (today - first_tx_date).days < MIN_HISTORY_DAYS:
            days_have = (today - first_tx_date).days if first_tx_date else 0
            return SkillResult(
                response_text=t_cached(
                    _STRINGS, "not_enough_data", lang,
                    namespace="cash_flow_forecast",
                    min_days=MIN_HISTORY_DAYS,
                    days_have=days_have,
                )
            )

        # Determine forecast horizon
        horizon_days = self._parse_horizon(intent_data, message.text or "")

        # Historical averages (last 30 and 90 days)
        avg_30 = await self._get_daily_averages(family_id, days=30)
        avg_90 = await self._get_daily_averages(family_id, days=90)

        # Recurring payments
        recurring = await self._get_recurring_payments(family_id)

        # Monthly totals for trend
        monthly = await self._get_monthly_totals(family_id, months=3)

        # Build data context
        data_lines = [
            f"Forecast horizon: {horizon_days} days",
            f"Currency: {context.currency}",
            f"Data history: {(today - first_tx_date).days} days",
            "",
            "Daily averages (last 30 days):",
            f"  Income: {avg_30['income']:.2f}/day",
            f"  Expenses: {avg_30['expense']:.2f}/day",
            f"  Net: {avg_30['income'] - avg_30['expense']:.2f}/day",
            "",
            "Daily averages (last 90 days):",
            f"  Income: {avg_90['income']:.2f}/day",
            f"  Expenses: {avg_90['expense']:.2f}/day",
            f"  Net: {avg_90['income'] - avg_90['expense']:.2f}/day",
        ]

        # Forecast projections
        daily_net = avg_30["income"] - avg_30["expense"]
        projected_net = daily_net * horizon_days
        data_lines.append(f"\nProjected net ({horizon_days} days): {projected_net:.2f}")
        data_lines.append(
            f"Projected income: {avg_30['income'] * horizon_days:.2f}"
        )
        data_lines.append(
            f"Projected expenses: {avg_30['expense'] * horizon_days:.2f}"
        )

        if recurring:
            total_recurring = sum(r["amount"] for r in recurring)
            data_lines.append(f"\nRecurring obligations: {total_recurring:.2f}/month")
            for r in recurring[:5]:
                data_lines.append(f"  {r['name']}: {r['amount']:.2f} ({r['frequency']})")

        if monthly:
            data_lines.append("\nMonthly trends:")
            for m in monthly:
                data_lines.append(
                    f"  {m['month']}: income {m['income']:.2f}, "
                    f"expenses {m['expense']:.2f}, net {m['net']:.2f}"
                )

        # Trend direction
        if len(monthly) >= 2:
            recent_net = monthly[0]["net"]
            prev_net = monthly[1]["net"]
            if recent_net > prev_net:
                data_lines.append("\nTrend: IMPROVING (net income increasing)")
            elif recent_net < prev_net:
                data_lines.append("\nTrend: DECLINING (net income decreasing)")
            else:
                data_lines.append("\nTrend: STABLE")

        data_text = "\n".join(data_lines)

        assembled = intent_data.get("_assembled")
        model = intent_data.get("_model", self.model)
        response = await generate_text(
            model=model,
            system_prompt=FORECAST_SYSTEM_PROMPT.format(language=lang),
            user_message=f"{message.text}\n\n--- DATA ---\n{data_text}",
            assembled_context=assembled,
        )

        # Prepend data summary so user sees what data was used
        history_days = (today - first_tx_date).days if first_tx_date else 0
        summary_line = t_cached(
            _STRINGS, "data_summary", lang, namespace="cash_flow_forecast",
            days=history_days,
            horizon=horizon_days,
            currency=context.currency,
        )
        response = f"<i>{summary_line}</i>\n\n{response}"

        return SkillResult(response_text=response)

    @staticmethod
    def _parse_horizon(intent_data: dict, text: str) -> int:
        """Parse forecast horizon from intent data or text."""
        text_lower = text.lower()
        if "90" in text_lower or "3 month" in text_lower or "3 мес" in text_lower:
            return 90
        if "60" in text_lower or "2 month" in text_lower or "2 мес" in text_lower:
            return 60
        return 30  # Default: 30 days

    @staticmethod
    async def _get_first_transaction_date(family_id: str) -> date | None:
        """Get the date of the earliest transaction."""
        async with async_session() as session:
            stmt = select(func.min(Transaction.date)).where(
                Transaction.family_id == uuid.UUID(family_id),
            )
            return await session.scalar(stmt)

    @staticmethod
    async def _get_daily_averages(
        family_id: str, days: int = 30,
    ) -> dict[str, float]:
        """Get average daily income and expense over a period."""
        cutoff = date.today() - timedelta(days=days)
        async with async_session() as session:
            for tx_type_name, tx_type in [
                ("income", TransactionType.income),
                ("expense", TransactionType.expense),
            ]:
                stmt = select(func.sum(Transaction.amount)).where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.type == tx_type,
                    Transaction.date >= cutoff,
                )
                total = await session.scalar(stmt) or 0
                if tx_type_name == "income":
                    income_total = float(total)
                else:
                    expense_total = float(total)

        return {
            "income": income_total / max(days, 1),
            "expense": expense_total / max(days, 1),
        }

    @staticmethod
    async def _get_weekly_pattern(family_id: str) -> list[dict]:
        """Get spending pattern by day of week."""
        cutoff = date.today() - timedelta(days=90)
        async with async_session() as session:
            stmt = (
                select(
                    func.extract("dow", Transaction.date).label("dow"),
                    func.avg(Transaction.amount).label("avg_amount"),
                )
                .where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.type == TransactionType.expense,
                    Transaction.date >= cutoff,
                )
                .group_by(func.extract("dow", Transaction.date))
                .order_by(func.extract("dow", Transaction.date))
            )
            rows = (await session.execute(stmt)).all()
            day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            return [
                {"day": day_names[int(r.dow)], "avg": float(r.avg_amount or 0)}
                for r in rows
            ]

    @staticmethod
    async def _get_recurring_payments(family_id: str) -> list[dict]:
        """Get active recurring payments."""
        async with async_session() as session:
            stmt = (
                select(RecurringPayment)
                .where(
                    RecurringPayment.family_id == uuid.UUID(family_id),
                    RecurringPayment.is_active.is_(True),
                )
                .order_by(RecurringPayment.amount.desc())
                .limit(10)
            )
            rows = (await session.scalars(stmt)).all()
            return [
                {
                    "name": r.name or r.merchant or "Recurring",
                    "amount": float(r.amount),
                    "frequency": r.frequency or "monthly",
                }
                for r in rows
            ]

    @staticmethod
    async def _get_monthly_totals(
        family_id: str, months: int = 3,
    ) -> list[dict]:
        """Get monthly income/expense totals for trend analysis."""
        results = []
        today = date.today()

        async with async_session() as session:
            for i in range(months):
                if today.month - i > 0:
                    m = today.month - i
                    y = today.year
                else:
                    m = today.month - i + 12
                    y = today.year - 1

                start = date(y, m, 1)
                if m == 12:
                    end = date(y + 1, 1, 1)
                else:
                    end = date(y, m + 1, 1)

                for tx_type_name, tx_type in [
                    ("income", TransactionType.income),
                    ("expense", TransactionType.expense),
                ]:
                    stmt = select(func.sum(Transaction.amount)).where(
                        Transaction.family_id == uuid.UUID(family_id),
                        Transaction.type == tx_type,
                        Transaction.date >= start,
                        Transaction.date < end,
                    )
                    total = await session.scalar(stmt) or 0
                    if tx_type_name == "income":
                        inc = float(total)
                    else:
                        exp = float(total)

                results.append({
                    "month": start.strftime("%B %Y"),
                    "income": inc,
                    "expense": exp,
                    "net": inc - exp,
                })

        return results


skill = CashFlowForecastSkill()
