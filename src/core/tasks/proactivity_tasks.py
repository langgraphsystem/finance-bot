"""Proactivity scheduled tasks — evaluates triggers for all users."""

import logging

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.tasks.broker import broker
from src.core.tasks.life_tasks import _send_telegram_message

logger = logging.getLogger(__name__)


@broker.task(schedule=[{"cron": "*/10 * * * *"}])
async def evaluate_proactive_triggers():
    """Every 10 min: check all active users for proactive data triggers.

    Time triggers (morning_brief, evening_recap) are handled by their
    own dedicated cron tasks. This task handles DataTriggers only.
    """
    from src.proactivity.engine import run_for_user

    async with async_session() as session:
        result = await session.execute(
            select(
                User.id,
                User.family_id,
                User.telegram_id,
                User.language,
            )
        )
        users = result.all()

    for user_id, family_id, telegram_id, language in users:
        try:
            # Load user profile for communication mode + suppressions
            comm_mode = "receipt"
            suppressed: list[str] = []

            async with async_session() as session:
                prof_result = await session.execute(
                    select(UserProfile).where(UserProfile.user_id == user_id).limit(1)
                )
                profile = prof_result.scalar_one_or_none()
                if profile:
                    comm_mode = profile.tone_preference or "receipt"
                    if profile.learned_patterns and isinstance(profile.learned_patterns, dict):
                        suppressed = profile.learned_patterns.get("suppressed_triggers", [])

            messages = await run_for_user(
                user_id=str(user_id),
                family_id=str(family_id),
                language=language or "en",
                communication_mode=comm_mode,
                suppressed_triggers=suppressed,
            )

            for msg in messages:
                await _send_telegram_message(telegram_id, msg["message"])
                logger.info(
                    "Proactive %s sent to user %s",
                    msg["trigger"],
                    telegram_id,
                )

        except Exception:
            logger.exception("Proactivity failed for user %s", user_id)
