"""Budget management skill — set and view spending limits."""

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.budget import Budget
from src.core.models.enums import BudgetPeriod, Scope
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

BUDGET_SYSTEM_PROMPT = """Ты помогаешь пользователю управлять бюджетами.
Извлеки из сообщения: категорию, сумму, период (weekly/monthly).
Если не указан период — по умолчанию monthly."""


class SetBudgetSkill:
    name = "set_budget"
    intents = ["set_budget"]
    model = "claude-haiku-4-5-20251001"

    @observe(name="set_budget")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        # Extract budget parameters from intent_data
        amount = intent_data.get("amount")
        category_name = intent_data.get("category")
        period_str = intent_data.get("period", "monthly")

        if not amount:
            return SkillResult(
                response_text="Укажите сумму бюджета. Например: «бюджет на продукты 30000»"
            )

        # Find category
        category_id = None
        matched_category = None
        for cat in context.categories:
            if category_name and cat["name"].lower() == category_name.lower():
                category_id = uuid.UUID(cat["id"])
                matched_category = cat["name"]
                break

        # Determine period
        period = BudgetPeriod.monthly
        if period_str and "week" in period_str.lower():
            period = BudgetPeriod.weekly

        async with async_session() as session:
            # Check if budget already exists for this category
            query = select(Budget).where(
                Budget.family_id == uuid.UUID(context.family_id),
                Budget.is_active == True,
            )
            if category_id:
                query = query.where(Budget.category_id == category_id)
            else:
                query = query.where(Budget.category_id == None)

            result = await session.execute(query)
            existing = result.scalar_one_or_none()

            if existing:
                existing.amount = Decimal(str(amount))
                existing.period = period
                action = "обновлён"
            else:
                budget = Budget(
                    family_id=uuid.UUID(context.family_id),
                    category_id=category_id,
                    scope=Scope.family,
                    amount=Decimal(str(amount)),
                    period=period,
                    alert_at=Decimal("0.8"),
                    is_active=True,
                )
                session.add(budget)
                action = "установлен"

            await session.commit()

        cat_text = f"«{matched_category}»" if matched_category else "общий"
        period_text = "в неделю" if period == BudgetPeriod.weekly else "в месяц"

        return SkillResult(
            response_text=f"Бюджет {action}: {cat_text} — ${amount} {period_text}\n"
                         f"Уведомлю при 80% и 100% использования."
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return BUDGET_SYSTEM_PROMPT


skill = SetBudgetSkill()
