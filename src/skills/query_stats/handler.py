"""Query stats skill — statistics and analytics."""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from src.core.charts import create_pie_chart
from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.mcp import run_analytics_query
from src.core.models.category import Category
from src.core.models.enums import TransactionType
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

STATS_SYSTEM_PROMPT = """Ты формируешь ответ о финансовой статистике.
Тебе передаются ГОТОВЫЕ числа из SQL. НИКОГДА не считай сам.
Оформи данные красиво и кратко (2-4 предложения).
Добавь сравнения и проценты, если данные позволяют."""


def _parse_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD string to date, return None on failure."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _resolve_period(
    intent_data: dict[str, Any],
) -> tuple[date, date, str]:
    """Resolve period from intent data into (start_date, end_date, label).

    Returns inclusive start and exclusive end (end = day after last included day).
    """
    today = date.today()
    period = intent_data.get("period") or "month"

    if period == "today":
        return today, today + timedelta(days=1), "сегодня"

    if period == "day":
        # Specific day from intent (e.g. "вчера", "15 января")
        day = _parse_date(intent_data.get("date")) or today
        return day, day + timedelta(days=1), day.strftime("%d.%m.%Y")

    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1), "эту неделю"

    if period == "prev_week":
        end = today - timedelta(days=today.weekday())  # Monday of this week
        start = end - timedelta(days=7)
        return start, end, "прошлую неделю"

    if period == "month":
        start = today.replace(day=1)
        return start, today + timedelta(days=1), "этот месяц"

    if period == "prev_month":
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month
        if today.month == 1:
            start = today.replace(year=today.year - 1, month=12, day=1)
        else:
            start = today.replace(month=today.month - 1, day=1)
        return start, last_month_end, "прошлый месяц"

    if period == "year":
        start = today.replace(month=1, day=1)
        return start, today + timedelta(days=1), "этот год"

    if period == "custom":
        date_from = _parse_date(intent_data.get("date_from"))
        date_to = _parse_date(intent_data.get("date_to"))
        if date_from and date_to:
            label = f"{date_from.strftime('%d.%m')} – {date_to.strftime('%d.%m.%Y')}"
            return date_from, date_to + timedelta(days=1), label
        if date_from:
            return date_from, today + timedelta(days=1), f"с {date_from.strftime('%d.%m.%Y')}"

    # Default: current month
    start = today.replace(day=1)
    return start, today + timedelta(days=1), "этот месяц"


def _calculate_previous_period(
    start_date: date,
    end_date: date,
    period: str,
) -> tuple[date, date]:
    """Calculate previous period boundaries based on current period type."""
    delta = end_date - start_date

    if period in ("today", "day"):
        prev_start = start_date - timedelta(days=1)
        prev_end = start_date
    elif period in ("week", "prev_week"):
        prev_start = start_date - timedelta(days=7)
        prev_end = start_date
    elif period == "year":
        prev_start = start_date.replace(year=start_date.year - 1)
        prev_end = end_date.replace(year=end_date.year - 1)
    elif period == "custom":
        prev_start = start_date - delta
        prev_end = start_date
    else:
        # month / prev_month
        if start_date.month == 1:
            prev_start = start_date.replace(year=start_date.year - 1, month=12)
        else:
            prev_start = start_date.replace(month=start_date.month - 1)
        prev_end = start_date
    return prev_start, prev_end


class QueryStatsSkill:
    name = "query_stats"
    intents = ["query_stats"]
    model = "claude-sonnet-4-5"

    async def _get_comparison_data(
        self,
        family_id: str,
        current_start: date,
        current_end: date,
        prev_start: date,
        prev_end: date,
    ) -> dict:
        """Get spending comparison between two periods."""
        async with async_session() as session:
            # Current period totals by category
            current_result = await session.execute(
                select(
                    Category.name,
                    func.sum(Transaction.amount).label("total"),
                )
                .join(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.date >= current_start,
                    Transaction.date < current_end,
                    Transaction.type == TransactionType.expense,
                )
                .group_by(Category.name)
            )
            current_data = {r[0]: float(r[1]) for r in current_result.all()}

            # Previous period totals by category
            prev_result = await session.execute(
                select(
                    Category.name,
                    func.sum(Transaction.amount).label("total"),
                )
                .join(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.family_id == uuid.UUID(family_id),
                    Transaction.date >= prev_start,
                    Transaction.date < prev_end,
                    Transaction.type == TransactionType.expense,
                )
                .group_by(Category.name)
            )
            prev_data = {r[0]: float(r[1]) for r in prev_result.all()}

        # Calculate changes
        all_categories = set(current_data.keys()) | set(prev_data.keys())
        comparison = []
        for cat in all_categories:
            curr = current_data.get(cat, 0)
            prev = prev_data.get(cat, 0)
            if prev > 0:
                change_pct = ((curr - prev) / prev) * 100
            elif curr > 0:
                change_pct = 100.0
            else:
                change_pct = 0.0
            comparison.append(
                {
                    "category": cat,
                    "current": curr,
                    "previous": prev,
                    "change_pct": change_pct,
                }
            )

        comparison.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

        return {
            "current_total": sum(current_data.values()),
            "previous_total": sum(prev_data.values()),
            "by_category": comparison,
        }

    @observe(name="query_stats")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        assembled = intent_data.get("_assembled")

        # MCP fallback for complex/free-form analytics queries
        if intent_data.get("complex_query") and settings.supabase_access_token:
            try:
                mcp_result = await run_analytics_query(message.text, context.family_id)
                if "недоступен" not in mcp_result.answer:
                    return SkillResult(response_text=mcp_result.answer)
            except Exception as e:
                logger.warning("MCP analytics fallback failed: %s", e)

        # Determine period from intent data
        start_date, end_date, period_label = _resolve_period(intent_data)
        period = intent_data.get("period") or "month"

        # Use assembled SQL stats for current month, own query for other periods
        total_income = Decimal("0")
        if period == "month" and assembled and assembled.sql_stats:
            sql_stats = assembled.sql_stats
            total = Decimal(str(sql_stats["total_expense"]))
            total_income = Decimal(str(sql_stats.get("total_income", 0)))
            stats = [(cat["name"], Decimal(str(cat["total"]))) for cat in sql_stats["by_category"]]
        else:
            # SQL query — LLM NEVER calculates
            async with async_session() as session:
                result = await session.execute(
                    select(
                        Category.name,
                        func.sum(Transaction.amount).label("total"),
                    )
                    .join(Category, Transaction.category_id == Category.id)
                    .where(
                        Transaction.family_id == uuid.UUID(context.family_id),
                        Transaction.date >= start_date,
                        Transaction.date < end_date,
                        Transaction.type == TransactionType.expense,
                    )
                    .group_by(Category.name)
                    .order_by(func.sum(Transaction.amount).desc())
                )
                stats = result.all()

                total_result = await session.execute(
                    select(func.sum(Transaction.amount)).where(
                        Transaction.family_id == uuid.UUID(context.family_id),
                        Transaction.date >= start_date,
                        Transaction.date < end_date,
                        Transaction.type == TransactionType.expense,
                    )
                )
                total = total_result.scalar() or Decimal("0")

                # Income query
                income_result = await session.execute(
                    select(func.sum(Transaction.amount)).where(
                        Transaction.family_id == uuid.UUID(context.family_id),
                        Transaction.date >= start_date,
                        Transaction.date < end_date,
                        Transaction.type == TransactionType.income,
                    )
                )
                total_income = income_result.scalar() or Decimal("0")

        if not stats and total_income == 0:
            return SkillResult(response_text=f"За {period_label} данных не найдено.")

        # Format data for LLM
        stats_text = "\n".join(f"- {name}: ${float(amount):.2f}" for name, amount in stats)

        user_content = f"Данные за {period_label}:\n"
        if total_income > 0:
            user_content += f"Итого доходов: ${float(total_income):.2f}\n"
        user_content += f"Итого расходов: ${float(total):.2f}\n"
        if total_income > 0:
            balance = total_income - total
            user_content += f"Баланс: ${float(balance):.2f}\n"
        user_content += (
            f"\nПо категориям расходов:\n{stats_text}\n\nВопрос пользователя: {message.text}"
        )

        # --- Period comparison ---
        prev_start, prev_end = _calculate_previous_period(start_date, end_date, period)
        try:
            comparison = await self._get_comparison_data(
                family_id=context.family_id,
                current_start=start_date,
                current_end=end_date,
                prev_start=prev_start,
                prev_end=prev_end,
            )

            if comparison["previous_total"] > 0:
                total_change = (
                    (comparison["current_total"] - comparison["previous_total"])
                    / comparison["previous_total"]
                    * 100
                )
                arrow = "\U0001f4c8" if total_change > 0 else "\U0001f4c9"
                comparison_text = (
                    "\n\u0421\u0440\u0430\u0432\u043d\u0435\u043d\u0438\u0435 "
                    "\u0441 \u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0438\u043c "
                    "\u043f\u0435\u0440\u0438\u043e\u0434\u043e\u043c:\n"
                )
                cur = comparison["current_total"]
                prev = comparison["previous_total"]
                comparison_text += (
                    f"\u0422\u0435\u043a\u0443\u0449\u0438\u0439: "
                    f"${cur:.2f}, "
                    f"\u041f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0438\u0439: "
                    f"${prev:.2f} "
                    f"({arrow}{total_change:+.1f}%)\n"
                )

                # Top changes
                for item in comparison["by_category"][:3]:
                    if item["change_pct"] != 0:
                        emoji = "\U0001f4c8" if item["change_pct"] > 0 else "\U0001f4c9"
                        comparison_text += (
                            f"  {emoji} {item['category']}: {item['change_pct']:+.1f}%\n"
                        )

                user_content += comparison_text
        except Exception as e:
            logger.warning("Failed to get comparison data: %s", e)

        # Generate response with LLM using assembled context if available
        client = anthropic_client()
        if assembled:
            # Use enriched system prompt (with memories) + history
            non_system = [m for m in assembled.messages if m["role"] != "system"]
            # Replace the last user message with stats-enriched content
            history = [m for m in non_system[:-1] if m["role"] in ("user", "assistant")]
            history.append({"role": "user", "content": user_content})
            prompt_data = PromptAdapter.for_claude(
                system=assembled.system_prompt,
                messages=history,
            )
        else:
            prompt_data = PromptAdapter.for_claude(
                system=STATS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )

        response = await client.messages.create(
            model=self.model,
            max_tokens=512,
            **prompt_data,
        )
        response_text = response.content[0].text

        # Generate chart
        chart_url = None
        if len(stats) >= 2:
            labels = [name for name, amount in stats]
            values = [float(amount) for _, amount in stats]
            chart_url = create_pie_chart(labels, values, f"Расходы за {period_label}")

        return SkillResult(
            response_text=response_text,
            chart_url=chart_url,
            buttons=[
                {
                    "text": "\U0001f4ca \u041f\u043e \u043d\u0435\u0434\u0435\u043b\u044f\u043c",
                    "callback": "stats:weekly",
                },
                {"text": "\U0001f4c8 \u0422\u0440\u0435\u043d\u0434", "callback": "stats:trend"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return STATS_SYSTEM_PROMPT


skill = QueryStatsSkill()
