"""Dead Letter Queue for failed Mem0 writes.

When Mem0 add_memory() fails (circuit breaker open, network error, etc.),
the failed write is enqueued in Redis for later retry by a Taskiq worker.

Uses idempotent keys (hash of user_id + category + content) to prevent
duplicates on retry.
"""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)

DLQ_KEY_PREFIX = "mem0_dlq"
DLQ_MAX_SIZE = 200  # Alert threshold
DLQ_ITEM_TTL = 86400  # 24h max retention


def _get_redis():
    from src.core.redis_client import get_redis
    return get_redis()


def _idempotency_key(user_id: str, content: str, category: str) -> str:
    """Generate a unique key to prevent duplicate DLQ entries."""
    raw = f"{user_id}:{category}:{content}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def enqueue_failed_memory(
    user_id: str,
    content: str,
    metadata: dict | None = None,
) -> None:
    """Enqueue a failed Mem0 write for later retry."""
    try:
        redis = _get_redis()
        category = (metadata or {}).get("category", "")
        idem_key = _idempotency_key(user_id, content, category)

        entry = json.dumps({
            "user_id": user_id,
            "content": content,
            "metadata": metadata or {},
            "idem_key": idem_key,
        }, ensure_ascii=False)

        key = f"{DLQ_KEY_PREFIX}:{user_id}"

        # Check for duplicate via idempotency key
        existing = await redis.lrange(key, 0, -1)
        for item in existing:
            try:
                parsed = json.loads(item)
                if parsed.get("idem_key") == idem_key:
                    return  # Already enqueued
            except (json.JSONDecodeError, TypeError):
                continue

        await redis.rpush(key, entry)
        await redis.expire(key, DLQ_ITEM_TTL)

        # Check queue size for alerting
        queue_size = await redis.llen(key)
        if queue_size > DLQ_MAX_SIZE:
            logger.warning("Mem0 DLQ for user %s has %d items (threshold: %d)",
                           user_id, queue_size, DLQ_MAX_SIZE)
    except Exception as e:
        logger.error("Failed to enqueue to Mem0 DLQ: %s", e)


async def dequeue_failed_memories(user_id: str, batch_size: int = 10) -> list[dict]:
    """Dequeue a batch of failed memories for retry."""
    try:
        redis = _get_redis()
        key = f"{DLQ_KEY_PREFIX}:{user_id}"
        items: list[dict] = []

        for _ in range(batch_size):
            raw = await redis.lpop(key)
            if raw is None:
                break
            try:
                items.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
        return items
    except Exception as e:
        logger.error("Failed to dequeue from Mem0 DLQ: %s", e)
        return []


async def get_all_dlq_user_ids() -> list[str]:
    """Get all user IDs that have pending DLQ items."""
    try:
        redis = _get_redis()
        keys = []
        async for key in redis.scan_iter(match=f"{DLQ_KEY_PREFIX}:*"):
            uid = key.decode() if isinstance(key, bytes) else key
            uid = uid.replace(f"{DLQ_KEY_PREFIX}:", "")
            keys.append(uid)
        return keys
    except Exception as e:
        logger.error("Failed to scan DLQ keys: %s", e)
        return []


async def retry_failed_memories(user_id: str) -> int:
    """Retry all failed memories for a user. Returns count of successfully retried."""
    from src.core.circuit_breaker import get_circuit
    from src.core.memory.mem0_client import add_memory

    cb = get_circuit("mem0")
    if not cb.can_execute():
        return 0  # Circuit still open, don't retry

    items = await dequeue_failed_memories(user_id)
    success_count = 0

    for item in items:
        try:
            await add_memory(
                item["content"],
                user_id=item["user_id"],
                metadata=item.get("metadata"),
            )
            success_count += 1
        except Exception as e:
            logger.warning("DLQ retry failed for user %s: %s", user_id, e)
            # Re-enqueue on failure
            await enqueue_failed_memory(
                item["user_id"],
                item["content"],
                item.get("metadata"),
            )
            break  # Stop retrying if Mem0 is still failing

    if success_count:
        logger.info("DLQ: retried %d/%d memories for user %s",
                     success_count, len(items), user_id)
    return success_count
