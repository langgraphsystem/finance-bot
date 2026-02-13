"""Audit logging — track all data modifications."""

import functools
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models.audit import AuditLog

logger = logging.getLogger(__name__)


async def log_action(
    session: AsyncSession,
    family_id: str,
    user_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    old_data: dict | None = None,
    new_data: dict | None = None,
) -> None:
    """Log an action to the audit trail."""
    entry = AuditLog(
        family_id=uuid.UUID(family_id),
        user_id=uuid.UUID(user_id),
        action=action,
        entity_type=entity_type,
        entity_id=uuid.UUID(entity_id),
        old_data=old_data,
        new_data=new_data,
    )
    session.add(entry)
    await session.flush()


def audited(entity_type: str):
    """Decorator to auto-log actions."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            logger.debug("Audit: %s on %s", func.__name__, entity_type)
            return result

        return wrapper

    return decorator
