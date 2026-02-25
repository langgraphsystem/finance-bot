"""Proactivity scheduled tasks — evaluates triggers for all users."""

import logging

from sqlalchemy import func, select

from src.core.db import async_session
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.tasks.broker import broker
from src.core.tasks.life_tasks import _send_telegram_message

logger = logging.getLogger(__name__)


def _normalize_language(lang: str | None) -> str:
    """Normalize language codes (e.g. en-US/en_US -> en)."""
    if not lang:
        return "en"
    normalized = lang.strip().lower().replace("_", "-")
    normalized = normalized.split("-", 1)[0]
    return normalized or "en"


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
                func.coalesce(UserProfile.preferred_language, User.language).label("language"),
                UserProfile.tone_preference,
                UserProfile.learned_patterns,
            ).outerjoin(UserProfile, UserProfile.user_id == User.id)
        )
        users = result.all()

    for (
        user_id,
        family_id,
        telegram_id,
        language,
        tone_preference,
        learned_patterns,
    ) in users:
        try:
            comm_mode = tone_preference or "receipt"
            suppressed: list[str] = []
            if learned_patterns and isinstance(learned_patterns, dict):
                suppressed = learned_patterns.get("suppressed_triggers", [])

            messages = await run_for_user(
                user_id=str(user_id),
                family_id=str(family_id),
                language=_normalize_language(language),
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
