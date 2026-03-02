"""Graph state recovery — resume interrupted graphs on server restart.

Scans the LangGraph checkpointer for threads that were interrupted
(HITL) or failed (transient errors) and attempts to recover them.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.observability import observe

logger = logging.getLogger(__name__)

# Only attempt recovery for threads interrupted within the last 24h
RECOVERY_WINDOW_HOURS = 24


@observe(name="recover_pending_graphs")
async def recover_pending_graphs() -> dict[str, int]:
    """Scan checkpointer for interrupted threads and log recovery candidates.

    This runs at app startup after ``setup_checkpointer()``.
    For HITL interrupts: logs them for manual follow-up (re-sending
    approval prompts requires gateway context we don't have at startup).
    For transient failures: logs them; automatic retry would need the
    original context which is in DLQ.

    Returns a summary dict: ``{"hitl_pending": N, "recovered": M}``.
    """
    from src.core.config import settings

    if not settings.ff_langgraph_checkpointer:
        return {"hitl_pending": 0, "recovered": 0}

    stats: dict[str, int] = {"hitl_pending": 0, "recovered": 0}

    try:
        from src.orchestrators.checkpointer import get_checkpointer

        cp = get_checkpointer()

        # Check if the checkpointer supports listing threads
        if not hasattr(cp, "alist"):
            logger.debug("Checkpointer does not support alist(); skipping recovery")
            return stats

        cutoff = datetime.now(UTC) - timedelta(hours=RECOVERY_WINDOW_HOURS)
        count = 0

        async for checkpoint_tuple in cp.alist({}):
            count += 1
            if count > 200:  # Safety cap
                break

            config = checkpoint_tuple.config if hasattr(checkpoint_tuple, "config") else {}
            thread_id = (
                config.get("configurable", {}).get("thread_id", "unknown")
            )

            checkpoint = (
                checkpoint_tuple.checkpoint
                if hasattr(checkpoint_tuple, "checkpoint")
                else {}
            )
            ts = checkpoint.get("ts")
            if ts:
                try:
                    ts_dt = datetime.fromisoformat(ts)
                    if ts_dt < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass

            # Check for pending interrupts
            pending_sends = checkpoint.get("pending_sends", [])
            if pending_sends:
                stats["hitl_pending"] += 1
                logger.info(
                    "Recovery: HITL thread pending — thread_id=%s",
                    thread_id,
                )

        if stats["hitl_pending"]:
            logger.info(
                "Recovery scan complete: %d HITL threads pending",
                stats["hitl_pending"],
            )
        else:
            logger.debug("Recovery scan complete: no pending threads found")

    except Exception as e:
        logger.warning("Graph recovery scan failed: %s", e)

    return stats


async def get_dlq_entries(
    graph_name: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch recent DLQ entries for monitoring/admin.

    Parameters
    ----------
    graph_name:
        Filter by graph name (e.g. "email", "brief", "booking").
    limit:
        Maximum entries to return.
    """
    from sqlalchemy import select

    from src.core.db import async_session
    from src.core.models.orchestrator_dlq import OrchestratorDLQ

    try:
        async with async_session() as session:
            query = (
                select(OrchestratorDLQ)
                .order_by(OrchestratorDLQ.created_at.desc())
                .limit(limit)
            )
            if graph_name:
                query = query.where(OrchestratorDLQ.graph_name == graph_name)

            result = await session.execute(query)
            entries = result.scalars().all()

            return [
                {
                    "id": str(e.id),
                    "graph_name": e.graph_name,
                    "thread_id": e.thread_id,
                    "user_id": str(e.user_id),
                    "error": e.error,
                    "retried": e.retried,
                    "created_at": e.created_at.isoformat() if e.created_at else "",
                }
                for e in entries
            ]
    except Exception as e:
        logger.error("Failed to fetch DLQ entries: %s", e)
        return []
