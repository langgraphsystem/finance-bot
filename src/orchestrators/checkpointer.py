"""LangGraph checkpointer factory.

Provides a PostgreSQL-backed checkpointer for durable graph state when a
database is available, with an in-memory fallback for testing.
"""

import logging

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from src.core.config import settings

logger = logging.getLogger(__name__)

_checkpointer: BaseCheckpointSaver | None = None


def _get_conninfo() -> str:
    """Normalise DATABASE_URL to a plain postgresql:// URI for psycopg."""
    conninfo = settings.database_url
    if conninfo.startswith("postgres://"):
        conninfo = conninfo.replace("postgres://", "postgresql://", 1)
    conninfo = conninfo.replace("postgresql+asyncpg://", "postgresql://")
    return conninfo


def get_checkpointer() -> BaseCheckpointSaver:
    """Return a shared checkpointer instance.

    - Production / staging: ``AsyncPostgresSaver`` backed by the app DB.
    - Testing / fallback: ``MemorySaver`` (no persistence across restarts).
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    if settings.app_env == "testing":
        _checkpointer = MemorySaver()
        return _checkpointer

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        conninfo = _get_conninfo()
        pool = AsyncConnectionPool(conninfo=conninfo, open=False)
        _checkpointer = AsyncPostgresSaver(conn=pool)
        logger.info("LangGraph checkpointer: AsyncPostgresSaver (PostgreSQL)")
    except Exception:
        logger.warning(
            "Failed to init PostgreSQL checkpointer, using MemorySaver fallback",
            exc_info=True,
        )
        _checkpointer = MemorySaver()

    return _checkpointer


async def is_healthy() -> bool:
    """Check if the checkpointer backend is responsive."""
    cp = get_checkpointer()
    if isinstance(cp, MemorySaver):
        return True
    try:
        if hasattr(cp, "conn") and hasattr(cp.conn, "getconn"):
            async with cp.conn.connection() as conn:
                await conn.execute("SELECT 1")
            return True
    except Exception:
        return False
    return True


async def setup_checkpointer() -> None:
    """Open the connection pool and create checkpoint tables if using PostgreSQL.

    Call once at app startup (e.g. in ``lifespan``).
    """
    cp = get_checkpointer()

    # Open the connection pool if it has one
    if hasattr(cp, "conn") and hasattr(cp.conn, "open"):
        try:
            await cp.conn.open()
            logger.info("Checkpointer connection pool opened")
        except Exception:
            logger.warning("Failed to open checkpointer pool", exc_info=True)

    if hasattr(cp, "setup"):
        try:
            await cp.setup()
            logger.info("LangGraph checkpoint tables ready")
        except Exception:
            logger.warning("Checkpoint table setup failed", exc_info=True)
