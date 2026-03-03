"""Billing tasks — daily token usage aggregation.

Computes cache hit ratios per model, overflow frequency, average per-layer
token usage, and total cost.  Results are logged to Langfuse as a daily
summary trace and to the Python logger for monitoring.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, cast, func, select
from sqlalchemy.types import Float

from src.core.db import async_session
from src.core.models.usage_log import UsageLog
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


@broker.task(schedule=[{"cron": "0 4 * * *"}])
async def aggregate_token_stats() -> dict:
    """Daily at 4am: aggregate token usage stats for the previous 24 hours.

    Computes per-model:
    - total_requests, success_rate
    - total_tokens_input, total_tokens_output
    - avg_tokens_input, avg_duration_ms
    - cache_hit_ratio  (fraction of calls where cache_read_tokens > 0)
    - total_cost_usd

    Plus global:
    - overflow_frequency  (fraction of calls that dropped memory layers)
    - overflow_layer_counts  (which layers were dropped most often)

    Returns the stats dict (useful for testing).
    """
    cutoff = datetime.now(UTC) - timedelta(hours=24)

    async with async_session() as session:
        # --- Per-model aggregation ---
        per_model_q = (
            select(
                UsageLog.model,
                func.count().label("total_requests"),
                func.sum(case((UsageLog.success.is_(True), 1), else_=0)).label(
                    "success_count"
                ),
                func.sum(UsageLog.tokens_input).label("total_tokens_input"),
                func.sum(UsageLog.tokens_output).label("total_tokens_output"),
                func.avg(cast(UsageLog.tokens_input, Float)).label("avg_tokens_input"),
                func.avg(cast(UsageLog.duration_ms, Float)).label("avg_duration_ms"),
                func.sum(
                    case((UsageLog.cache_read_tokens > 0, 1), else_=0)
                ).label("cache_hit_count"),
                func.sum(UsageLog.cache_read_tokens).label("total_cache_read"),
                func.sum(UsageLog.cache_creation_tokens).label("total_cache_creation"),
                func.sum(UsageLog.cost_usd).label("total_cost_usd"),
            )
            .where(UsageLog.created_at >= cutoff)
            .group_by(UsageLog.model)
        )
        model_rows = (await session.execute(per_model_q)).all()

        # --- Global overflow stats ---
        overflow_q = (
            select(
                func.count().label("total"),
                func.sum(
                    case(
                        (UsageLog.overflow_layers_dropped.isnot(None), 1),
                        else_=0,
                    )
                ).label("overflow_count"),
            )
            .where(UsageLog.created_at >= cutoff)
        )
        overflow_row = (await session.execute(overflow_q)).one()

        # --- Overflow layer breakdown ---
        layer_q = (
            select(UsageLog.overflow_layers_dropped)
            .where(
                UsageLog.created_at >= cutoff,
                UsageLog.overflow_layers_dropped.isnot(None),
            )
        )
        overflow_raw = (await session.execute(layer_q)).scalars().all()

    # Parse per-model stats
    model_stats: dict[str, dict] = {}
    for row in model_rows:
        model_name = row.model or "unknown"
        total = row.total_requests or 0
        cache_hits = row.cache_hit_count or 0
        model_stats[model_name] = {
            "total_requests": total,
            "success_rate": round((row.success_count or 0) / total, 3) if total else 0,
            "total_tokens_input": row.total_tokens_input or 0,
            "total_tokens_output": row.total_tokens_output or 0,
            "avg_tokens_input": round(row.avg_tokens_input or 0, 1),
            "avg_duration_ms": round(row.avg_duration_ms or 0, 1),
            "cache_hit_ratio": round(cache_hits / total, 3) if total else 0,
            "total_cache_read_tokens": row.total_cache_read or 0,
            "total_cache_creation_tokens": row.total_cache_creation or 0,
            "total_cost_usd": float(row.total_cost_usd or 0),
        }

    # Parse overflow stats
    total_requests = overflow_row.total or 0
    overflow_count = overflow_row.overflow_count or 0
    overflow_frequency = (
        round(overflow_count / total_requests, 3) if total_requests else 0
    )

    # Count which layers get dropped most
    layer_counts: dict[str, int] = {}
    for raw in overflow_raw:
        for layer in raw.split(","):
            layer = layer.strip()
            if layer:
                layer_counts[layer] = layer_counts.get(layer, 0) + 1

    stats = {
        "period": "24h",
        "computed_at": datetime.now(UTC).isoformat(),
        "total_requests": total_requests,
        "overflow_frequency": overflow_frequency,
        "overflow_layer_counts": layer_counts,
        "models": model_stats,
    }

    # Log to Python logger
    logger.info(
        "Token stats (24h): %d requests, overflow=%.1f%%, models=%d",
        total_requests,
        overflow_frequency * 100,
        len(model_stats),
    )
    for model_name, ms in model_stats.items():
        logger.info(
            "  %s: %d reqs, cache_hit=%.1f%%, avg_input=%d, cost=$%.4f",
            model_name,
            ms["total_requests"],
            ms["cache_hit_ratio"] * 100,
            ms["avg_tokens_input"],
            ms["total_cost_usd"],
        )

    # Log to Langfuse as a summary trace
    _log_to_langfuse(stats)

    return stats


def _log_to_langfuse(stats: dict) -> None:
    """Send aggregated stats to Langfuse as a trace event."""
    try:
        from src.core.observability import get_langfuse

        langfuse = get_langfuse()
        if not langfuse:
            return

        langfuse.trace(
            name="daily_token_stats",
            metadata={
                "total_requests": stats["total_requests"],
                "overflow_frequency": stats["overflow_frequency"],
                "overflow_layers": stats["overflow_layer_counts"],
                **{
                    f"model_{name}": model_data
                    for name, model_data in stats["models"].items()
                },
            },
        )
    except Exception as e:
        logger.debug("Failed to log token stats to Langfuse: %s", e)
