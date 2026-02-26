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

        # Use the same connection string as SQLAlchemy but with raw asyncpg
        conninfo = settings.database_url
        # asyncpg wants postgresql:// not postgres://
        if conninfo.startswith("postgres://"):
            conninfo = conninfo.replace("postgres://", "postgresql://", 1)
        # Strip +asyncpg driver suffix if present — asyncpg uses plain URI
        conninfo = conninfo.replace("postgresql+asyncpg://", "postgresql://")

        _checkpointer = AsyncPostgresSaver.from_conn_string(conninfo)
        logger.info("LangGraph checkpointer: AsyncPostgresSaver (PostgreSQL)")
    except Exception:
        logger.warning(
            "Failed to init PostgreSQL checkpointer, using MemorySaver fallback",
            exc_info=True,
        )
        _checkpointer = MemorySaver()

    return _checkpointer


async def setup_checkpointer() -> None:
    """Create checkpoint tables if using PostgreSQL saver.

    Call once at app startup (e.g. in ``lifespan``).
    """
    cp = get_checkpointer()
    if hasattr(cp, "setup"):
        try:
            await cp.setup()
            logger.info("LangGraph checkpoint tables ready")
        except Exception:
            logger.warning("Checkpoint table setup failed", exc_info=True)
