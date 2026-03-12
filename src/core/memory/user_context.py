"""Layer 2: User context — session state in PostgreSQL."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db import async_session
from src.core.models.enums import ConversationState
from src.core.models.user_context import UserContext

SESSION_IDLE_TIMEOUT = timedelta(hours=6)
SESSION_MAX_MESSAGES = 50


async def get_user_context(session: AsyncSession, user_id: str) -> UserContext | None:
    result = await session.execute(
        select(UserContext).where(UserContext.user_id == uuid.UUID(user_id))
    )
    return result.scalar_one_or_none()


async def update_user_context(
    session: AsyncSession,
    user_id: str,
    **kwargs: Any,
) -> None:
    await session.execute(
        update(UserContext).where(UserContext.user_id == uuid.UUID(user_id)).values(**kwargs)
    )
    await session.commit()


async def create_user_context(
    session: AsyncSession,
    user_id: str,
    family_id: str,
    *,
    commit: bool = True,
) -> UserContext:
    ctx = UserContext(
        user_id=uuid.UUID(user_id),
        family_id=uuid.UUID(family_id),
        session_id=uuid.uuid4(),
        conversation_state=ConversationState.normal,
        message_count=0,
    )
    session.add(ctx)
    if commit:
        await session.commit()
    else:
        await session.flush()
    return ctx


async def increment_message_count(session: AsyncSession, user_id: str) -> int:
    ctx = await get_user_context(session, user_id)
    if ctx:
        new_count = ctx.message_count + 1
        await update_user_context(session, user_id, message_count=new_count)
        return new_count
    return 0


def should_rotate_session(
    ctx: UserContext,
    *,
    now: datetime | None = None,
) -> bool:
    """Start a new session after long inactivity or oversized conversations."""
    now = now or datetime.now(UTC)
    if int(ctx.message_count or 0) >= SESSION_MAX_MESSAGES:
        return True

    updated_at = ctx.updated_at
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return (now - updated_at) >= SESSION_IDLE_TIMEOUT


async def ensure_active_session(
    session: AsyncSession,
    user_id: str,
    family_id: str,
    *,
    now: datetime | None = None,
) -> UserContext:
    """Load or create the current user session and rotate stale sessions."""
    ctx = await get_user_context(session, user_id)
    if ctx is None:
        return await create_user_context(session, user_id, family_id, commit=False)

    if should_rotate_session(ctx, now=now):
        ctx.session_id = uuid.uuid4()
        ctx.message_count = 0
        await session.flush()

    return ctx


async def ensure_active_user_session(
    user_id: str,
    family_id: str,
    *,
    now: datetime | None = None,
) -> str:
    """Ensure a live session exists before memory retrieval or persistence."""
    async with async_session() as session:
        ctx = await ensure_active_session(session, user_id, family_id, now=now)
        await session.commit()
        return str(ctx.session_id)


async def get_current_session_id(
    session: AsyncSession,
    user_id: str,
    *,
    allow_stale: bool = False,
    now: datetime | None = None,
) -> uuid.UUID | None:
    """Return the active session_id for this user."""
    ctx = await get_user_context(session, user_id)
    if ctx is None:
        return None
    if not allow_stale and should_rotate_session(ctx, now=now):
        return None
    return ctx.session_id
