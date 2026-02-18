"""Pending action storage for pre-flight confirmation of destructive operations."""

import json
import uuid
from datetime import UTC, datetime

from src.core.db import redis

PENDING_ACTION_TTL = 600  # 10 minutes


async def store_pending_action(
    intent: str,
    user_id: str,
    family_id: str,
    action_data: dict,
) -> str:
    """Store a pending action in Redis, return the pending_id."""
    pending_id = str(uuid.uuid4())[:8]
    payload = {
        "intent": intent,
        "user_id": user_id,
        "family_id": family_id,
        "action_data": action_data,
        "created_at": datetime.now(UTC).isoformat(),
    }
    key = f"pending_action:{pending_id}"
    await redis.set(key, json.dumps(payload, default=str), ex=PENDING_ACTION_TTL)
    return pending_id


async def get_pending_action(pending_id: str) -> dict | None:
    """Retrieve a pending action from Redis."""
    key = f"pending_action:{pending_id}"
    raw = await redis.get(key)
    if not raw:
        return None
    return json.loads(raw)


async def delete_pending_action(pending_id: str) -> None:
    """Delete a pending action from Redis."""
    await redis.delete(f"pending_action:{pending_id}")
