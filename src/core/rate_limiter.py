"""Tiered rate limiting — different limits based on operation cost.

Expensive operations (browser automation, document generation, heavy LLM)
get stricter limits than simple queries. Uses Redis INCR + EXPIRE.
"""

import logging

from src.core.db import redis

logger = logging.getLogger(__name__)

# Tier definitions: limit = max calls, window = time window in seconds
RATE_LIMITS: dict[str, dict[str, int]] = {
    "default": {"limit": 30, "window": 60},
    "llm_heavy": {"limit": 10, "window": 60},
    "browser": {"limit": 3, "window": 300},
    "document_gen": {"limit": 5, "window": 300},
    "image_gen": {"limit": 5, "window": 300},
}

# Map expensive intents to their cost tier
INTENT_TIER_MAP: dict[str, str] = {
    # LLM-heavy (complex multi-step reasoning)
    "complex_query": "llm_heavy",
    "financial_summary": "llm_heavy",
    "tax_estimate": "llm_heavy",
    "cash_flow_forecast": "llm_heavy",
    "compare_documents": "llm_heavy",
    "analyze_document": "llm_heavy",
    # Browser automation (Playwright sessions)
    "browser_action": "browser",
    "web_action": "browser",
    # Document generation (WeasyPrint / E2B sandbox)
    "generate_document": "document_gen",
    "generate_presentation": "document_gen",
    "generate_spreadsheet": "document_gen",
    "generate_invoice_pdf": "document_gen",
    "convert_document": "document_gen",
    "merge_documents": "document_gen",
    # Image generation
    "generate_image": "image_gen",
    "generate_card": "image_gen",
}


async def check_rate_limit(user_id: str, intent: str) -> tuple[bool, str]:
    """Check if user is within rate limit for this intent.

    Returns (allowed: bool, tier: str).
    """
    tier = INTENT_TIER_MAP.get(intent, "default")
    config = RATE_LIMITS[tier]
    key = f"rate:{tier}:{user_id}"

    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, config["window"])
        allowed = count <= config["limit"]
        if not allowed:
            logger.warning(
                "Rate limit hit: user=%s tier=%s count=%d/%d",
                user_id,
                tier,
                count,
                config["limit"],
            )
        return allowed, tier
    except Exception:
        # If Redis is down, allow the request (fail open)
        logger.exception("Rate limit check failed, allowing request")
        return True, tier


def get_limit_message(tier: str, language: str = "en") -> str:
    """User-friendly rate limit message."""
    config = RATE_LIMITS.get(tier, RATE_LIMITS["default"])
    window_min = config["window"] // 60

    messages = {
        "en": f"Too many requests. Please wait {window_min} minute(s) and try again.",
        "ru": f"Слишком много запросов. Подождите {window_min} мин. и попробуйте снова.",
        "es": f"Demasiadas solicitudes. Espera {window_min} minuto(s) e intenta de nuevo.",
    }
    return messages.get(language, messages["en"])
