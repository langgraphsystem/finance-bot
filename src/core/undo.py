"""Undo window — time-limited undo after quick actions.

Phase 9: Undo also removes associated Mem0 facts via transaction_id.
"""

import json
import logging
import uuid

from sqlalchemy import delete

from src.core.db import async_session, redis
from src.core.models.life_event import LifeEvent
from src.core.models.task import Task
from src.core.models.transaction import Transaction

logger = logging.getLogger(__name__)

UNDO_TTL = 120  # 2 minutes

UNDO_INTENTS: set[str] = {
    "add_expense",
    "add_income",
    "create_task",
    "track_food",
    "track_drink",
}

TABLE_MODEL_MAP: dict[str, type] = {
    "transactions": Transaction,
    "tasks": Task,
    "life_events": LifeEvent,
}


async def store_undo(
    user_id: str,
    intent: str,
    record_id: str,
    table: str,
) -> None:
    """Store undo payload in Redis. Key: undo:{user_id}, TTL 120s.

    Phase 9: record_id is also used as transaction_id for Mem0 sync.
    """
    payload = {
        "intent": intent,
        "record_id": record_id,
        "table": table,
        "transaction_id": record_id,  # Phase 9: link to Mem0 facts
    }
    await redis.set(f"undo:{user_id}", json.dumps(payload), ex=UNDO_TTL)


async def pop_undo(user_id: str) -> dict | None:
    """Pop undo payload (get + delete). Returns None if expired."""
    key = f"undo:{user_id}"
    raw = await redis.get(key)
    if not raw:
        return None
    await redis.delete(key)
    return json.loads(raw)


async def execute_undo(user_id: str, family_id: str) -> str:
    """Execute undo: delete the record + clean up Mem0 facts."""
    data = await pop_undo(user_id)
    if not data:
        return "Nothing to undo (window expired)."

    table = data["table"]
    record_id = data["record_id"]
    transaction_id = data.get("transaction_id", record_id)
    model = TABLE_MODEL_MAP.get(table)
    if not model:
        logger.error("Unknown table for undo: %s", table)
        return "Undo failed: unknown record type."

    try:
        async with async_session() as session:
            await session.execute(
                delete(model).where(
                    model.id == uuid.UUID(record_id),
                    model.family_id == uuid.UUID(family_id),
                )
            )
            await session.commit()

        # Phase 9: Remove associated Mem0 facts
        await _cleanup_mem0_facts(user_id, transaction_id)

        logger.info("Undo: deleted %s/%s for user %s", table, record_id, user_id)
        return "Undone."
    except Exception as e:
        logger.error("Undo failed for %s/%s: %s", table, record_id, e, exc_info=True)
        return "Undo failed. Please try again."


async def _cleanup_mem0_facts(user_id: str, transaction_id: str) -> None:
    """Remove Mem0 facts linked to a transaction_id (Phase 9).

    Searches recent memories for matching transaction_id in metadata
    and deletes them to keep Mem0 in sync with the database.
    """
    try:
        from src.core.memory.mem0_client import delete_memory, search_memories

        # Search for facts that mention this transaction
        results = await search_memories(
            transaction_id, user_id, limit=5,
            filters={"transaction_id": transaction_id},
        )
        for mem in results:
            mem_id = mem.get("id")
            if mem_id:
                await delete_memory(mem_id, user_id)
                logger.debug("Undo: removed Mem0 fact %s for transaction %s",
                             mem_id, transaction_id)
    except Exception as e:
        logger.debug("Mem0 cleanup on undo failed (non-critical): %s", e)
