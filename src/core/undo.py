"""Undo window — time-limited undo after quick actions."""

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
    """Store undo payload in Redis. Key: undo:{user_id}, TTL 120s."""
    payload = {"intent": intent, "record_id": record_id, "table": table}
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
    """Execute undo: delete the record. Returns confirmation text."""
    data = await pop_undo(user_id)
    if not data:
        return "Nothing to undo (window expired)."

    table = data["table"]
    record_id = data["record_id"]
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
        logger.info("Undo: deleted %s/%s for user %s", table, record_id, user_id)
        return "Undone."
    except Exception as e:
        logger.error("Undo failed for %s/%s: %s", table, record_id, e, exc_info=True)
        return "Undo failed. Please try again."
