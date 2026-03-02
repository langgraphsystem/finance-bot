"""Agentic Plan Cache — Redis-backed caching for LLM execution plans.

Stores tool-call sequences (plans) from successful LLM executions.
On cache hit, the cached plan is replayed without re-asking the LLM
for routing decisions — saving ~50% cost and ~27% latency for
repetitive tasks like morning_brief, invoice, export.

Key format: ``plan:{scope}:{params_hash}``

Usage::

    from src.core.plan_cache import plan_cache

    # Check for cached plan
    cached = await plan_cache.get("brief", user_id=uid, intent="morning_brief")
    if cached:
        return cached["result"]

    # ... execute normally ...

    # Cache the result
    await plan_cache.put("brief", result, user_id=uid, intent="morning_brief")
"""

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL = 86400  # 24 hours
BRIEF_TTL = 300  # 5 minutes for brief/recap outputs
TOOL_PLAN_TTL = 43200  # 12 hours for tool-call sequences


class PlanCache:
    """Redis-backed cache for LLM execution plans and synthesized results.

    Two usage patterns:

    1. **Result caching** (brief/recap): Cache the final synthesized text
       so repeated triggers within TTL skip the entire graph.

    2. **Tool plan caching** (route_with_tools): Cache the sequence of
       tool calls the LLM chose. On cache hit, replay the plan directly
       (execute same tools with fresh data, skip LLM routing).
    """

    @staticmethod
    def compute_hash(**kwargs: Any) -> str:
        """Compute a stable 16-char hex hash from keyword arguments."""
        raw = json.dumps(kwargs, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    async def get(scope: str, **params: Any) -> dict[str, Any] | None:
        """Retrieve a cached plan/result.

        Parameters
        ----------
        scope:
            Cache namespace (e.g. ``"brief"``, ``"tools"``).
        **params:
            Parameters that identify this plan (hashed into the key).
        """
        try:
            from src.core.db import redis

            h = PlanCache.compute_hash(**params)
            key = f"plan:{scope}:{h}"
            data = await redis.get(key)
            if data:
                logger.debug("Plan cache HIT: %s", key)
                return json.loads(data)
        except Exception as e:
            logger.debug("Plan cache get failed: %s", e)
        return None

    @staticmethod
    async def put(
        scope: str,
        plan: dict[str, Any],
        ttl: int = DEFAULT_TTL,
        **params: Any,
    ) -> None:
        """Store a plan/result in cache.

        Parameters
        ----------
        scope:
            Cache namespace.
        plan:
            The data to cache (tool sequence, synthesized text, etc.).
        ttl:
            Time-to-live in seconds.
        **params:
            Parameters that identify this plan (hashed into the key).
        """
        try:
            from src.core.db import redis

            h = PlanCache.compute_hash(**params)
            key = f"plan:{scope}:{h}"
            await redis.set(key, json.dumps(plan, default=str), ex=ttl)
            logger.debug("Plan cache PUT: %s (ttl=%ds)", key, ttl)
        except Exception as e:
            logger.debug("Plan cache put failed: %s", e)

    @staticmethod
    async def invalidate(scope: str, **params: Any) -> None:
        """Remove a cached plan/result."""
        try:
            from src.core.db import redis

            h = PlanCache.compute_hash(**params)
            key = f"plan:{scope}:{h}"
            await redis.delete(key)
            logger.debug("Plan cache INVALIDATE: %s", key)
        except Exception as e:
            logger.debug("Plan cache invalidate failed: %s", e)


# Module-level singleton
plan_cache = PlanCache()
