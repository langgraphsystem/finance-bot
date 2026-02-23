"""Weekly digest cron task — sends cross-domain weekly summary to all users.

Runs every Sunday at 09:00 UTC. Uses the WeeklyDigestSkill to collect
spending, tasks, life events, and calendar data, then synthesizes via
Claude Sonnet and delivers to the user's primary channel.
"""

import logging
import uuid

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.user import User
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


async def _send_telegram_message(telegram_id: int, text: str) -> None:
    """Send a message via Telegram Bot API."""
    from src.core.config import settings

    try:
        from aiogram import Bot

        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode="HTML",
        )
        await bot.session.close()
    except Exception as e:
        logger.error("Failed to send digest to %s: %s", telegram_id, e)


async def _build_user_context(user_id: str, family_id: str):
    """Build a minimal SessionContext for digest generation."""
    from src.core.context import SessionContext

    return SessionContext(
        user_id=user_id,
        family_id=family_id,
        role="owner",
        language="en",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


@broker.task(schedule=[{"cron": "0 9 * * 0"}])  # Sunday 09:00 UTC
async def send_weekly_digests() -> None:
    """Generate and send weekly digests for all users."""
    from src.core.life_helpers import get_communication_mode
    from src.gateway.types import IncomingMessage, MessageType
    from src.skills.weekly_digest.handler import WeeklyDigestSkill

    skill = WeeklyDigestSkill()

    async with async_session() as session:
        result = await session.execute(
            select(User.id, User.family_id, User.telegram_id)
        )
        users = result.all()

    sent = 0
    for user_id, family_id, telegram_id in users:
        if not telegram_id:
            continue

        try:
            # Respect communication mode
            mode = await get_communication_mode(str(user_id))
            if mode == "silent":
                continue

            ctx = await _build_user_context(str(user_id), str(family_id))

            # Create a synthetic message to drive the skill
            message = IncomingMessage(
                id=str(uuid.uuid4()),
                user_id=str(telegram_id),
                chat_id=str(telegram_id),
                type=MessageType.text,
                text="weekly digest",
            )

            result = await skill.execute(message, ctx, {})

            if result.response_text:
                await _send_telegram_message(telegram_id, result.response_text)
                sent += 1
                logger.info("Weekly digest sent to user %s", telegram_id)

        except Exception as e:
            logger.error("Weekly digest failed for user %s: %s", user_id, e)

    logger.info("Weekly digests sent: %d/%d users", sent, len(users))
