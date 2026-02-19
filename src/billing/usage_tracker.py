"""Usage tracker — logs LLM token usage per request to usage_logs table."""

import logging
import uuid
from decimal import Decimal

from sqlalchemy import insert

from src.core.db import async_session
from src.core.models.usage_log import UsageLog

logger = logging.getLogger(__name__)

# Approximate cost per 1K tokens by model family (USD).
_COST_PER_1K: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (0.015, 0.075),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-haiku-4-5": (0.0008, 0.004),
    "gpt-5.2": (0.005, 0.015),
    "gemini-3-flash-preview": (0.0001, 0.0004),
    "gemini-3-pro-preview": (0.00125, 0.005),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Estimate USD cost from token counts."""
    rates = _COST_PER_1K.get(model, (0.001, 0.005))
    cost = (tokens_in / 1000) * rates[0] + (tokens_out / 1000) * rates[1]
    return Decimal(str(round(cost, 6)))


async def log_usage(
    *,
    user_id: str,
    family_id: str,
    domain: str = "",
    skill: str = "",
    model: str = "",
    tokens_input: int = 0,
    tokens_output: int = 0,
    duration_ms: int = 0,
    success: bool = True,
) -> None:
    """Persist a usage log entry. Fire-and-forget — errors are logged, not raised."""
    try:
        cost = _estimate_cost(model, tokens_input, tokens_output)
        async with async_session() as session:
            await session.execute(
                insert(UsageLog).values(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(user_id),
                    family_id=uuid.UUID(family_id),
                    domain=domain,
                    skill=skill,
                    model=model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    cost_usd=cost,
                    duration_ms=duration_ms,
                    success=success,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to log usage")
