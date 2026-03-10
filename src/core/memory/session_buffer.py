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
import time

from src.core.db import redis

logger = logging.getLogger(__name__)

SESSION_BUFFER_TTL = 1800  # 30 minutes, rolling
REDIS_KEY_PREFIX = "session_facts"
MAX_BUFFER_ITEMS = 20


def _parse_buffer_entry(item: str | bytes | dict) -> dict | None:
    """Parse a single Redis entry without failing the whole buffer."""
    try:
        if isinstance(item, dict):
            parsed = item
        else:
            parsed = json.loads(item)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    fact = str(parsed.get("fact", "")).strip()
    if not fact:
        return None
    category = str(parsed.get("category", "")).strip()
    domain = str(parsed.get("domain", "")).strip()
    return {
        "fact": fact,
        "category": category,
        "domain": domain,
        "ts": parsed.get("ts"),
    }


def _dedupe_buffer_entries(items: list[str | bytes | dict]) -> list[dict]:
    """Keep only the latest fact per category/fact so fresh values win."""
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in reversed(items):
        parsed = _parse_buffer_entry(item)
        if not parsed:
            continue
        dedupe_key = parsed["category"] or parsed["fact"]
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(parsed)
    deduped.reverse()
    return deduped


async def get_session_buffer(user_id: str, domains: set[str] | None = None) -> list[dict]:
    """Get all session buffer facts for a user."""
    key = f"{REDIS_KEY_PREFIX}:{user_id}"
    try:
        raw = await redis.lrange(key, 0, -1)
        facts = _dedupe_buffer_entries(raw)
        if not domains:
            return facts
        return [fact for fact in facts if not fact.get("domain") or fact.get("domain") in domains]
    except Exception as e:
        logger.debug("Session buffer read failed: %s", e)
        return []


async def update_session_buffer(
    user_id: str, fact: str, category: str = "", domain: str = ""
) -> None:
    """Add a fact to the session buffer. Resets rolling TTL.

    Args:
        domain: Mem0 domain tag for the fact (GAP-M4). Allows context assembly
                to filter buffer facts by domain relevance.
    """
    key = f"{REDIS_KEY_PREFIX}:{user_id}"
    entry = json.dumps(
        {"fact": fact, "category": category, "domain": domain, "ts": time.time()},
        ensure_ascii=False,
    )
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
