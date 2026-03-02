"""Layer 1.5: In-session buffer — immediate fact storage in Redis.

Solves the critical race condition:
  User says "salary now 6000" → async_mem0_update not yet complete →
  next query within seconds gets the OLD Mem0 value.

The session buffer stores facts extracted in the current session with a
rolling 30-minute TTL. During context assembly, buffer facts are loaded
FIRST and win on conflicts with Mem0 results.

Buffer is cleared after successful async_mem0_update confirms persistence.
"""

import json
import logging

from src.core.db import redis

logger = logging.getLogger(__name__)

SESSION_BUFFER_TTL = 1800  # 30 minutes, rolling
REDIS_KEY_PREFIX = "session_facts"
MAX_BUFFER_ITEMS = 20


async def get_session_buffer(user_id: str) -> list[dict]:
    """Get all session buffer facts for a user."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}"
    try:
        raw = await redis.lrange(key, 0, -1)
        return [json.loads(item) for item in raw]
    except Exception as e:
        logger.debug("Session buffer read failed: %s", e)
        return []


async def update_session_buffer(user_id: str, fact: str, category: str = "") -> None:
    """Add a fact to the session buffer. Resets rolling TTL."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}"
    entry = json.dumps({"fact": fact, "category": category}, ensure_ascii=False)
    try:
        await redis.rpush(key, entry)
        await redis.ltrim(key, -MAX_BUFFER_ITEMS, -1)
        await redis.expire(key, SESSION_BUFFER_TTL)
    except Exception as e:
        logger.debug("Session buffer write failed: %s", e)


async def clear_session_buffer(user_id: str) -> None:
    """Clear the session buffer after Mem0 persistence is confirmed."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}"
    try:
        await redis.delete(key)
    except Exception as e:
        logger.debug("Session buffer clear failed: %s", e)


def format_buffer_block(facts: list[dict]) -> str:
    """Format session buffer facts as a context block."""
    if not facts:
        return ""
    lines = [f"- {f['fact']}" for f in facts if f.get("fact")]
    if not lines:
        return ""
    return "\n\n## Новая информация (текущая сессия):\n" + "\n".join(lines)
