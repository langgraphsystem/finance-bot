"""Add income skill — records an income transaction."""

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from src.core.audit import log_action
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import Scope, TransactionType
from src.core.models.transaction import Transaction
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

INCOME_SYSTEM_PROMPT = """Ты записываешь доход пользователя.
Извлеки из сообщения: сумму, источник, описание, дату.

Категории пользователя:
{categories}"""


class AddIncomeSkill:
    name = "add_income"
    intents = ["add_income"]
    model = "gpt-5.2"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        amount = intent_data.get("amount")
        description = intent_data.get("description") or intent_data.get("merchant")
        scope = intent_data.get("scope", "business" if context.business_type else "family")
        tx_date = intent_data.get("date") or date.today().isoformat()

        if not amount:
            return SkillResult(response_text="Не удалось определить сумму дохода. Укажите сумму.")

        # Find income category
        category_id = None
        for cat in context.categories:
            if cat.get("name", "").lower() in ("доход", "income", "зарплата"):
                category_id = cat.get("id")
                break
        if not category_id and context.categories:
            category_id = context.categories[0].get("id")

        if not category_id:
            return SkillResult(response_text="Нет категорий для записи дохода.")

        async with async_session() as session:
            tx = Transaction(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                category_id=uuid.UUID(category_id),
                type=TransactionType.income,
                amount=Decimal(str(amount)),
                description=description,
                date=date.fromisoformat(tx_date) if isinstance(tx_date, str) else tx_date,
                scope=Scope(scope) if scope else Scope.family,
                ai_confidence=1.0,
            )
            session.add(tx)
            await session.flush()

            await log_action(
                session=session,
                family_id=context.family_id,
                user_id=context.user_id,
                action="create",
                entity_type="transaction",
                entity_id=str(tx.id),
                new_data={
                    "amount": float(tx.amount),
                    "description": description,
                    "type": "income",
                },
            )

            await session.commit()
            tx_id = str(tx.id)

        response = f"Доход записан: ${amount}"
        if description:
            response += f" ({description})"

        return SkillResult(
            response_text=response,
            buttons=[
                {"text": "✅ Верно", "callback": f"confirm:{tx_id}"},
                {"text": "❌ Отмена", "callback": f"cancel:{tx_id}"},
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        categories = "\n".join(f"- {c['name']} ({c.get('scope', '')})" for c in context.categories)
        return INCOME_SYSTEM_PROMPT.format(categories=categories)


skill = AddIncomeSkill()
