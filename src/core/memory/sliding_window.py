"""Layer 1: Sliding window — last N messages in Redis + PostgreSQL fallback.

Uses rolling TTL: each new message resets the 24h expiry timer,
so active conversations don't lose context at midnight.

If Redis is empty (restart, TTL expiry), falls back to PostgreSQL
``conversation_messages`` table so context is never fully lost.
"""

import json
import logging

from src.core.db import redis

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "conv"
DEFAULT_WINDOW_SIZE = 10
TTL_SECONDS = 86400  # 24 hours — rolling, reset on each message


def _parse_message(item: str | bytes | dict) -> dict | None:
    """Parse a single window entry without failing the whole history."""
    try:
        if isinstance(item, dict):
            parsed = item
        else:
            parsed = json.loads(item)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    role = str(parsed.get("role", "")).strip()
    content = str(parsed.get("content", "")).strip()
    if not role or not content:
        return None
    intent = parsed.get("intent")
    return {
        "role": role,
        "content": content,
        "intent": intent,
    }


async def add_message(
    user_id: str,
    role: str,
    content: str,
    intent: str | None = None,
) -> None:
    """Add a message to the sliding window. Resets rolling TTL."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}:messages"
    message = json.dumps(
        {
            "role": role,
            "content": content,
            "intent": intent,
        },
        ensure_ascii=False,
    )

    try:
        await redis.rpush(key, message)
        await redis.ltrim(key, -DEFAULT_WINDOW_SIZE, -1)
        # Rolling TTL — reset on every message so active conversations persist
        await redis.expire(key, TTL_SECONDS)
    except Exception as e:
        logger.warning("Redis sliding window write failed: %s", e)


async def _fallback_from_postgres(user_id: str, limit: int) -> list[dict]:
    """Fallback: load recent messages from PostgreSQL when Redis is empty."""
    try:
        import uuid

        from sqlalchemy import select

        from src.core.db import async_session
        from src.core.models.conversation import ConversationMessage

        async with async_session() as session:
            result = await session.execute(
                select(
                    ConversationMessage.role,
                    ConversationMessage.content,
                    ConversationMessage.intent,
                )
                .where(ConversationMessage.user_id == uuid.UUID(user_id))
                .order_by(ConversationMessage.created_at.desc())
                .limit(limit)
            )
            rows = result.all()

        if not rows:
            return []

        messages = [
            {
                "role": row.role.value if hasattr(row.role, "value") else str(row.role),
                "content": row.content,
                "intent": row.intent,
            }
            for row in reversed(rows)  # oldest first
        ]
        logger.info(
            "Sliding window fallback: loaded %d messages from PostgreSQL for %s",
            len(messages), user_id,
        )

        # GAP-M7: Warm Redis cache so subsequent requests skip DB fallback
        try:
            key = f"{REDIS_KEY_PREFIX}:{user_id}:messages"
            pipe = redis.pipeline()
            for msg in messages:
                pipe.rpush(key, json.dumps(msg, ensure_ascii=False))
            pipe.ltrim(key, -DEFAULT_WINDOW_SIZE, -1)
            pipe.expire(key, TTL_SECONDS)
            await pipe.execute()
        except Exception as warm_err:
            logger.debug("Redis cache warming failed (non-critical): %s", warm_err)

        return messages
    except Exception as e:
        logger.warning("PostgreSQL fallback for sliding window failed: %s", e)
        return []


async def get_recent_messages(
    user_id: str,
    limit: int = DEFAULT_WINDOW_SIZE,
) -> list[dict]:
    """Get recent messages from sliding window (Redis primary, PostgreSQL fallback)."""
    try:
        key = f"{REDIS_KEY_PREFIX}:{user_id}:messages"
        raw_messages = await redis.lrange(key, -limit, -1)
        if raw_messages:
            parsed = [msg for msg in (_parse_message(m) for m in raw_messages) if msg]
            if parsed:
                return parsed
    except Exception as e:
        logger.warning("Redis sliding window read failed: %s", e)

    # Fallback to PostgreSQL when Redis is empty or unavailable
    return await _fallback_from_postgres(user_id, limit)


async def count_recent_intents(
    user_id: str,
    intent: str,
    last_n: int = 6,
) -> int:
    """Count how many of the last N user messages had the given intent."""
    window_limit = max(last_n * 3, DEFAULT_WINDOW_SIZE)
    messages = await get_recent_messages(user_id, limit=window_limit)
    user_messages = [m for m in messages if m.get("role") == "user"]
    return sum(1 for m in user_messages[-last_n:] if m.get("intent") == intent)


async def clear_messages(user_id: str) -> None:
    """Clear all messages for a user."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}:messages"
    try:
        await redis.delete(key)
    except Exception as e:
        logger.warning("Redis sliding window clear failed: %s", e)
