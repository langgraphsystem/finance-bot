"""Rate limiting — Redis-based per-user message throttle."""

import logging
from src.core.config import settings
from src.core.db import redis

logger = logging.getLogger(__name__)


async def check_rate_limit(user_id: str) -> bool:
    """Check if user is within rate limit.

    Returns True if allowed, False if rate-limited.
    Uses Redis INCR + EXPIRE pattern (sliding window per minute).
    """
    key = f"rate:{user_id}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 60)  # 1 minute window
        return count <= settings.rate_limit_per_minute
    except Exception as e:
        logger.warning("Rate limit check failed: %s", e)
        return True  # Fail open
