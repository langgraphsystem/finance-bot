"""Undo last transaction skill."""

import logging
import uuid
from typing import Any

from sqlalchemy import delete, desc, select

from src.core.audit import log_action
from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.transaction import Transaction
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

UNDO_SYSTEM_PROMPT = """Ты помогаешь пользователю отменить последнюю операцию.
Сообщи результат кратко и понятно."""


class UndoLastSkill:
    name = "undo_last"
    intents = ["undo_last"]
    model = "claude-haiku-4-5"

    @observe(name="undo_last")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Find last transaction and ask for confirmation before deleting."""
        async with async_session() as session:
            result = await session.execute(
                select(Transaction)
                .where(
                    Transaction.user_id == uuid.UUID(context.user_id),
                    Transaction.family_id == uuid.UUID(context.family_id),
                )
                .order_by(desc(Transaction.created_at))
                .limit(1)
            )
            tx = result.scalar_one_or_none()

            if not tx:
                return SkillResult(
                    response_text="У вас нет транзакций для отмены."
                )

            tx_info = (
                f"{tx.type.value}: {tx.amount} "
                f"({tx.merchant or tx.description or 'без описания'})"
            )
            tx_id = str(tx.id)

        # Store pending action — require user confirmation
        from src.core.pending_actions import store_pending_action

        pending_id = await store_pending_action(
            intent="undo_last",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "tx_id": tx_id,
                "tx_type": tx.type.value,
                "tx_amount": str(tx.amount),
                "tx_merchant": tx.merchant,
                "tx_description": tx.description,
            },
        )

        return SkillResult(
            response_text=f"Удалить транзакцию?\n\n{tx_info}",
            buttons=[
                {
                    "text": "🗑 Удалить",
                    "callback": f"confirm_action:{pending_id}",
                },
                {
                    "text": "❌ Отмена",
                    "callback": f"cancel_action:{pending_id}",
                },
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return UNDO_SYSTEM_PROMPT


async def execute_undo(
    action_data: dict, user_id: str, family_id: str
) -> str:
    """Actually delete the transaction. Called after user confirms."""
    tx_id = action_data["tx_id"]

    try:
        async with async_session() as session:
            await session.execute(
                delete(Transaction).where(Transaction.id == uuid.UUID(tx_id))
            )
            await log_action(
                session=session,
                user_id=user_id,
                family_id=family_id,
                action="undo_last",
                entity_type="transaction",
                entity_id=tx_id,
                old_data={
                    "type": action_data.get("tx_type"),
                    "amount": action_data.get("tx_amount"),
                    "merchant": action_data.get("tx_merchant"),
                },
                new_data=None,
            )
            await session.commit()

        tx_info = (
            f"{action_data.get('tx_type', 'expense')}: "
            f"{action_data.get('tx_amount', '?')} "
            f"({action_data.get('tx_merchant') or action_data.get('tx_description') or ''})"
        )
        logger.info("User %s undid transaction %s", user_id, tx_id)
        return f"Отменено: {tx_info}"
    except Exception as e:
        logger.error("Undo transaction %s failed: %s", tx_id, e)
        return "Ошибка при удалении транзакции."


skill = UndoLastSkill()
