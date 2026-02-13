"""Undo last transaction skill."""
import logging
import uuid
from typing import Any

from sqlalchemy import select, delete, desc

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.audit import log_action
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
    model = "claude-haiku-4-5-20251001"

    @observe(name="undo_last")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Find and delete the user's last transaction."""
        async with async_session() as session:
            # Find user's last transaction
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
                return SkillResult(response_text="У вас нет транзакций для отмены.")

            # Store info before deletion for the response
            tx_info = (
                f"{tx.type.value}: {tx.amount} "
                f"({tx.merchant or tx.description or 'без описания'})"
            )
            tx_id = str(tx.id)

            # Delete the transaction
            await session.execute(
                delete(Transaction).where(Transaction.id == tx.id)
            )

            # Log to audit
            await log_action(
                session=session,
                user_id=context.user_id,
                family_id=context.family_id,
                action="undo_last",
                entity_type="transaction",
                entity_id=tx_id,
                old_data={
                    "type": tx.type.value,
                    "amount": str(tx.amount),
                    "merchant": tx.merchant,
                },
                new_data=None,
            )

            await session.commit()

        logger.info("User %s undid transaction %s", context.user_id, tx_id)
        return SkillResult(
            response_text=f"Отменено: {tx_info}",
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return UNDO_SYSTEM_PROMPT


skill = UndoLastSkill()
