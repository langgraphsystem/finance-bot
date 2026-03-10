"""Add income skill — records an income transaction."""

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from src.core.access import get_default_visibility
from src.core.audit import log_action
from src.core.context import SessionContext
from src.core.db import get_session
from src.core.models.enums import Scope, TransactionType
from src.core.models.transaction import Transaction
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

INCOME_SYSTEM_PROMPT = """Ты записываешь доход пользователя.
Извлеки из сообщения: сумму, источник, описание, дату.

Категории пользователя:
{categories}"""


register_strings("add_income", {"en": {}, "ru": {}, "es": {}})

_INCOME_CATEGORY_KEYWORDS = (
    "доход",
    "income",
    "зарплата",
    "salary",
    "фриланс",
    "freelance",
    "бизнес",
    "business",
    "кэшбэк",
    "cashback",
    "бонус",
    "bonus",
    "инвести",
    "investment",
    "аренд",
    "rental",
    "подработ",
)


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
        if not context.has_permission("create_finance"):
            return SkillResult(response_text="У вас нет прав для добавления доходов.")

        amount = intent_data.get("amount")
        description = intent_data.get("description") or intent_data.get("merchant")
        scope = intent_data.get("scope", "business" if context.business_type else "family")
        if context.role == "member":
            scope = "family"
        tx_date = intent_data.get("date") or date.today().isoformat()

        if not amount:
            return SkillResult(response_text="Не удалось определить сумму дохода. Укажите сумму.")

        category_name = intent_data.get("category")
        category_id = self._resolve_income_category(
            category_name=category_name,
            description=description,
            merchant=intent_data.get("merchant"),
            context=context,
        )

        if not category_id:
            return SkillResult(
                response_text=(
                    "Не нашёл подходящую категорию дохода. "
                    "Укажите категорию дохода точнее."
                ),
            )

        async with get_session() as session:
            tx = Transaction(
                family_id=uuid.UUID(context.family_id),
                user_id=uuid.UUID(context.user_id),
                category_id=uuid.UUID(category_id),
                type=TransactionType.income,
                amount=Decimal(str(amount)),
                description=description,
                date=date.fromisoformat(tx_date) if isinstance(tx_date, str) else tx_date,
                scope=Scope(scope) if scope else Scope.family,
                visibility=get_default_visibility(Scope(scope)).value,
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

        intent_data["_record_id"] = tx_id
        intent_data["_record_table"] = "transactions"

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

    def _resolve_income_category(
        self,
        category_name: str | None,
        description: str | None,
        merchant: str | None,
        context: SessionContext,
    ) -> str | None:
        requested = (category_name or "").strip().lower()
        if requested:
            for cat in context.categories:
                if cat.get("name", "").lower() == requested:
                    return cat.get("id")

        for cat in context.categories:
            cat_name = cat.get("name", "").lower()
            if any(keyword in cat_name for keyword in _INCOME_CATEGORY_KEYWORDS):
                return cat.get("id")

        parts = (requested, description or "", merchant or "")
        combined_hint = " ".join(p.lower() for p in parts if p)
        if combined_hint:
            for cat in context.categories:
                cat_name = cat.get("name", "").lower()
                if cat_name and cat_name in combined_hint:
                    return cat.get("id")

        return None


skill = AddIncomeSkill()
