"""GDPR compliance — export, delete, rectify user data."""

import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db import redis
from src.core.memory.mem0_client import delete_all_memories, get_all_memories
from src.core.models.audit import AuditLog
from src.core.models.conversation import ConversationMessage
from src.core.models.transaction import Transaction
from src.core.models.user_context import UserContext

logger = logging.getLogger(__name__)


class MemoryGDPR:
    """GDPR operations for user data."""

    async def export_user_data(self, session: AsyncSession, user_id: str) -> dict:
        """GDPR Art. 15: Right of access — export all user data."""
        uid = uuid.UUID(user_id)

        # Transactions
        tx_result = await session.execute(select(Transaction).where(Transaction.user_id == uid))
        transactions = [
            {
                "id": str(t.id),
                "type": t.type.value,
                "amount": float(t.amount),
                "merchant": t.merchant,
                "date": t.date.isoformat(),
                "scope": t.scope.value,
            }
            for t in tx_result.scalars()
        ]

        # Conversation logs
        msg_result = await session.execute(
            select(ConversationMessage).where(ConversationMessage.user_id == uid)
        )
        messages = [
            {
                "role": m.role.value,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msg_result.scalars()
        ]

        # Mem0 memories
        try:
            memories = await get_all_memories(user_id)
        except Exception:
            memories = []

        return {
            "user_id": user_id,
            "transactions": transactions,
            "conversation_logs": messages,
            "memories": memories,
        }

    async def delete_user_data(self, session: AsyncSession, user_id: str) -> bool:
        """GDPR Art. 17: Right to erasure — delete all user data."""
        uid = uuid.UUID(user_id)

        # Delete from PostgreSQL
        await session.execute(delete(ConversationMessage).where(ConversationMessage.user_id == uid))
        await session.execute(delete(Transaction).where(Transaction.user_id == uid))
        await session.execute(delete(AuditLog).where(AuditLog.user_id == uid))
        await session.execute(delete(UserContext).where(UserContext.user_id == uid))
        await session.commit()

        # Delete from Mem0
        try:
            await delete_all_memories(user_id)
        except Exception as e:
            logger.warning("Mem0 deletion failed: %s", e)

        # Delete from Redis
        try:
            keys = []
            async for key in redis.scan_iter(f"conv:{user_id}:*"):
                keys.append(key)
            if keys:
                await redis.delete(*keys)
        except Exception as e:
            logger.warning("Redis deletion failed: %s", e)

        logger.info("All data deleted for user %s", user_id)
        return True

    async def rectify_memory(self, user_id: str, old: str, new: str) -> None:
        """GDPR Art. 16: Right to rectification."""
        from src.core.memory.mem0_client import get_memory

        memory = get_memory()
        results = memory.search(old, user_id=user_id, limit=5)
        result_list = results.get("results", []) if isinstance(results, dict) else results
        for mem in result_list:
            memory.update(mem["id"], new)
        logger.info("Rectified memory for user %s: '%s' → '%s'", user_id, old, new)
