"""Correct category skill — updates the category of the last transaction."""

import logging
import uuid
from typing import Any

from sqlalchemy import select

from src.core.audit import log_action
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.category import Category
from src.core.models.transaction import Transaction
from src.core.tasks.memory_tasks import async_update_merchant_mapping
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


class CorrectCategorySkill:
    name = "correct_category"
    intents = ["correct_category"]
    model = "claude-haiku-4-5"

    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        new_category_name = intent_data.get("category")
        if not new_category_name:
            return SkillResult(
                response_text="Какую категорию поставить?",
                buttons=[
                    {"text": c["name"], "callback": f"cat:{c['id']}"}
                    for c in context.categories[:6]
                ],
            )

        # Find matching category
        new_cat_id = None
        for cat in context.categories:
            if cat["name"].lower() == new_category_name.lower():
                new_cat_id = cat["id"]
                break

        if not new_cat_id:
            return SkillResult(
                response_text=(f"Категория \u00ab{new_category_name}\u00bb не найдена."),
            )

        # Get last transaction
        async with async_session() as session:
            result = await session.execute(
                select(Transaction)
                .where(Transaction.user_id == uuid.UUID(context.user_id))
                .order_by(Transaction.created_at.desc())
                .limit(1)
            )
            tx = result.scalar_one_or_none()
            if not tx:
                return SkillResult(response_text="Нет транзакций для исправления.")

            old_category_name = "Unknown"
            # Get old category name
            old_cat = await session.execute(select(Category).where(Category.id == tx.category_id))
            old_cat_obj = old_cat.scalar_one_or_none()
            if old_cat_obj:
                old_category_name = old_cat_obj.name

            tx.category_id = uuid.UUID(new_cat_id)
            tx.is_corrected = True

            await log_action(
                session=session,
                family_id=context.family_id,
                user_id=context.user_id,
                action="update",
                entity_type="transaction",
                entity_id=str(tx.id),
                old_data={"category": old_category_name},
                new_data={"category": new_category_name},
            )

            await session.commit()

        merchant = tx.merchant
        scope_value = tx.scope.value if tx.scope else "family"

        return SkillResult(
            response_text=f"Исправлено: {old_category_name} -> {new_category_name}",
            background_tasks=[
                lambda: (
                    async_update_merchant_mapping.kiq(
                        context.family_id, merchant, new_cat_id, scope_value
                    )
                    if merchant
                    else None
                ),
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        categories = "\n".join(f"- {c['name']} ({c.get('scope', '')})" for c in context.categories)
        return f"Ты исправляешь категорию транзакции.\n\nКатегории:\n{categories}"


skill = CorrectCategorySkill()
