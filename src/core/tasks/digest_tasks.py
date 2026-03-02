"""Weekly digest cron task — sends digest every Sunday at 09:00 UTC."""

import logging
import os

from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


@broker.task(schedule=[{"cron": "0 9 * * 0"}])
async def send_weekly_digests() -> None:
    """Send weekly digest to all active users."""
    from sqlalchemy import text

    from src.core.db import async_session

    logger.info("Starting weekly digest delivery")
    try:
        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT u.id as user_id, u.family_id, up.telegram_id,
                           up.language, up.currency, up.comm_mode
                    FROM users u
                    JOIN user_profiles up ON u.id = up.user_id
                    WHERE up.telegram_id IS NOT NULL
                """)
            )
            users = result.all()
    except Exception as e:
        logger.error("Failed to fetch users for weekly digest: %s", e)
        return

    sent = 0
    for user in users:
        if user.comm_mode == "silent":
            continue

        try:
            from src.core.context import SessionContext
            from src.gateway.types import IncomingMessage, MessageType
            from src.skills.weekly_digest.handler import WeeklyDigestSkill

            ctx = SessionContext(
                user_id=str(user.user_id),
                family_id=str(user.family_id),
                role="owner",
                language=user.language or "en",
                currency=user.currency or "USD",
                business_type=None,
                categories=[],
                merchant_mappings=[],
            )
            msg = IncomingMessage(
                id="digest",
                user_id=str(user.telegram_id),
                chat_id=str(user.telegram_id),
                type=MessageType.text,
                text="weekly digest",
            )
            digest_skill = WeeklyDigestSkill()
            skill_result = await digest_skill.execute(msg, ctx, {})

            if skill_result.response_text:
                from aiogram import Bot

                bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=skill_result.response_text,
                    parse_mode="HTML",
                )
                await bot.session.close()
                sent += 1
        except Exception as e:
            logger.warning(
                "Failed to send digest to user %s: %s", user.user_id, e
            )

    logger.info("Weekly digest sent to %d users", sent)
