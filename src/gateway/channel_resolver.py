"""Channel resolver — looks up internal user from channel-specific user IDs.

When a message arrives from Slack/WhatsApp/SMS, we need to map the
channel-specific user ID to our internal User. This module handles
that lookup via the ``channel_links`` table.
"""

import logging
import uuid

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.channel_link import ChannelLink
from src.core.models.enums import ChannelType
from src.core.models.user import User

logger = logging.getLogger(__name__)


async def resolve_user(
    channel: str, channel_user_id: str
) -> tuple[str | None, str | None]:
    """Resolve a channel user to (user_id, family_id).

    Returns (None, None) if the channel user is not linked to any account.
    """
    try:
        ch_type = ChannelType(channel)
    except ValueError:
        # Telegram users are looked up by telegram_id directly, not via channel_links
        if channel == "telegram":
            return await _resolve_telegram(channel_user_id)
        return None, None

    async with async_session() as session:
        result = await session.execute(
            select(ChannelLink).where(
                ChannelLink.channel == ch_type,
                ChannelLink.channel_user_id == channel_user_id,
            )
        )
        link = result.scalar_one_or_none()
        if link:
            return str(link.user_id), str(link.family_id)

    return None, None


async def link_channel(
    user_id: str,
    family_id: str,
    channel: str,
    channel_user_id: str,
    channel_chat_id: str | None = None,
    is_primary: bool = False,
) -> ChannelLink:
    """Create a channel link for an existing user.

    If a link already exists for this channel+channel_user_id, update it.
    """
    ch_type = ChannelType(channel)

    async with async_session() as session:
        result = await session.execute(
            select(ChannelLink).where(
                ChannelLink.channel == ch_type,
                ChannelLink.channel_user_id == channel_user_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.user_id = uuid.UUID(user_id)
            existing.family_id = uuid.UUID(family_id)
            existing.channel_chat_id = channel_chat_id
            existing.is_primary = is_primary
            await session.commit()
            return existing

        link = ChannelLink(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            family_id=uuid.UUID(family_id),
            channel=ch_type,
            channel_user_id=channel_user_id,
            channel_chat_id=channel_chat_id,
            is_primary=is_primary,
        )
        session.add(link)
        await session.commit()
        return link


async def _resolve_telegram(telegram_id_str: str) -> tuple[str | None, str | None]:
    """Fallback: resolve Telegram user via users.telegram_id."""
    try:
        tid = int(telegram_id_str)
    except ValueError:
        return None, None

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == tid)
        )
        user = result.scalar_one_or_none()
        if user:
            return str(user.id), str(user.family_id)
    return None, None
