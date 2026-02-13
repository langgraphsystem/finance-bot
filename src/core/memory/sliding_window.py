"""Layer 1: Sliding window — last N messages in Redis + PostgreSQL backup."""

import json
import logging

from src.core.db import redis

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "conv"
DEFAULT_WINDOW_SIZE = 10
TTL_SECONDS = 86400  # 24 hours


async def add_message(
    user_id: str,
    role: str,
    content: str,
    intent: str | None = None,
) -> None:
    """Add a message to the sliding window."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}:messages"
    message = json.dumps(
        {
            "role": role,
            "content": content,
            "intent": intent,
        },
        ensure_ascii=False,
    )

    await redis.rpush(key, message)
    await redis.ltrim(key, -DEFAULT_WINDOW_SIZE, -1)
    await redis.expire(key, TTL_SECONDS)


async def get_recent_messages(
    user_id: str,
    limit: int = DEFAULT_WINDOW_SIZE,
) -> list[dict]:
    """Get recent messages from sliding window."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}:messages"
    raw_messages = await redis.lrange(key, -limit, -1)
    return [json.loads(m) for m in raw_messages]


async def clear_messages(user_id: str) -> None:
    """Clear all messages for a user."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}:messages"
    await redis.delete(key)
