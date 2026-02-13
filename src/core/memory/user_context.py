"""Layer 2: User context — session state in PostgreSQL."""

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models.user_context import UserContext
from src.core.models.enums import ConversationState


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
        update(UserContext)
        .where(UserContext.user_id == uuid.UUID(user_id))
        .values(**kwargs)
    )
    await session.commit()


async def create_user_context(
    session: AsyncSession,
    user_id: str,
    family_id: str,
) -> UserContext:
    ctx = UserContext(
        user_id=uuid.UUID(user_id),
        family_id=uuid.UUID(family_id),
        session_id=uuid.uuid4(),
        conversation_state=ConversationState.normal,
        message_count=0,
    )
    session.add(ctx)
    await session.commit()
    return ctx


async def increment_message_count(session: AsyncSession, user_id: str) -> int:
    ctx = await get_user_context(session, user_id)
    if ctx:
        new_count = ctx.message_count + 1
        await update_user_context(session, user_id, message_count=new_count)
        return new_count
    return 0
