"""Add expense skill — records an expense transaction."""

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from src.core.audit import log_action
from src.core.categorization import categorize_transaction
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.enums import Scope, TransactionType
from src.core.models.transaction import Transaction
from src.core.tasks.memory_tasks import (
    async_check_budget,
    async_mem0_update,
    async_update_merchant_mapping,
)
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

EXPENSE_SYSTEM_PROMPT = """Ты записываешь расход пользователя.
Извлеки из сообщения: сумму, мерчант, категорию, дату.
Если мерчант известен, используй маппинг из памяти.

Категории пользователя:
{categories}

Известные мерчанты:
{mappings}"""


class AddExpenseSkill:
    name = "add_expense"
    intents = ["add_expense"]
    model = "claude-haiku-4-5"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        amount = intent_data.get("amount")
        merchant = intent_data.get("merchant")
        category_name = intent_data.get("category")
        scope = intent_data.get("scope", "family")
        tx_date = intent_data.get("date") or date.today().isoformat()
        confidence = intent_data.get("confidence", 0.5)

        if not amount:
            return SkillResult(
                response_text="Не удалось определить сумму. Укажите, пожалуйста, сумму расхода."
            )

        # Resolve category from mappings or intent data
        category_id = self._resolve_category(category_name, context)
        if not category_id:
            return SkillResult(
                response_text=f"Не нашёл категорию «{category_name}». Выберите:",
                buttons=[
                    {"text": c["name"], "callback": f"cat:{c['id']}:{amount}"}
                    for c in context.categories[:6]
                ],
            )

        # High confidence: auto-record
        if confidence > 0.85:
            async with async_session() as session:
                tx = Transaction(
                    family_id=uuid.UUID(context.family_id),
                    user_id=uuid.UUID(context.user_id),
                    category_id=uuid.UUID(category_id),
                    type=TransactionType.expense,
                    amount=Decimal(str(amount)),
                    merchant=merchant,
                    date=date.fromisoformat(tx_date) if isinstance(tx_date, str) else tx_date,
                    scope=Scope(scope) if scope else Scope.family,
                    ai_confidence=confidence,
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
                        "category": category_name,
                        "type": "expense",
                    },
                )

                await session.commit()
                tx_id = str(tx.id)

            response = f"Записал: {category_name} ${amount}"
            if merchant:
                response += f", {merchant}"

            return SkillResult(
                response_text=response,
                buttons=[
                    {"text": "✅ Верно", "callback": f"confirm:{tx_id}"},
                    {"text": "✏️ Категория", "callback": f"correct:{tx_id}"},
                    {"text": "❌ Отмена", "callback": f"cancel:{tx_id}"},
                ],
                background_tasks=[
                    lambda: async_mem0_update.kiq(context.user_id, message.text or ""),
                    lambda: (
                        async_update_merchant_mapping.kiq(
                            context.family_id, merchant, category_id, scope
                        )
                        if merchant
                        else None
                    ),
                    lambda: async_check_budget.kiq(context.family_id, category_id),
                ],
            )

        # Low confidence: ask for confirmation
        return SkillResult(
            response_text=f"{merchant or ''} ${amount} — это «{category_name}»?",
            buttons=[
                {"text": "✅ Верно", "callback": f"pending_confirm:{amount}:{category_id}:{scope}"},
                {"text": "✏️ Изменить", "callback": f"pending_correct:{amount}"},
            ],
        )

    def _resolve_category(self, category_name: str | None, context: SessionContext) -> str | None:
        if not category_name:
            return None
        for cat in context.categories:
            if cat.get("name", "").lower() == category_name.lower():
                return cat.get("id")
        return None

    async def _resolve_category_hybrid(
        self,
        category_name: str | None,
        merchant: str | None,
        description: str,
        context: SessionContext,
    ) -> tuple[str | None, str | None, float]:
        """Resolve category using simple match first, then hybrid RAG pipeline.

        Returns (category_id, category_name, confidence).
        """
        # Fast path: simple name match from intent data
        if category_name:
            cat_id = self._resolve_category(category_name, context)
            if cat_id:
                return cat_id, category_name, 0.95

        # Slow path: hybrid categorization pipeline (rules -> RAG -> LLM)
        try:
            prediction = await categorize_transaction(
                description=description,
                merchant=merchant,
                family_id=context.family_id,
                available_categories=context.categories,
            )
            if prediction:
                return prediction.category_id, prediction.category_name, prediction.confidence
        except Exception:
            logger.warning("Hybrid categorization failed, falling back", exc_info=True)

        return None, category_name, 0.0

    def get_system_prompt(self, context: SessionContext) -> str:
        categories = "\n".join(f"- {c['name']} ({c.get('scope', '')})" for c in context.categories)
        mappings = "\n".join(
            f"- {m.get('merchant_pattern', '')} → {m.get('category_name', '')}"
            for m in context.merchant_mappings
        )
        return EXPENSE_SYSTEM_PROMPT.format(categories=categories, mappings=mappings)


skill = AddExpenseSkill()
