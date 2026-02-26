"""Proactivity scheduled tasks — evaluates triggers for all users."""

import logging

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session
from src.core.locale_resolution import resolve_notification_locale
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.notifications_pkg.dispatch import send_telegram_message
from src.core.tasks.broker import broker

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
                UserProfile.preferred_language,
                UserProfile.notification_language,
                UserProfile.timezone,
                UserProfile.timezone_source,
                UserProfile.tone_preference,
                UserProfile.learned_patterns,
            ).outerjoin(UserProfile, UserProfile.user_id == User.id)
        )
        users = result.all()

    sent_count = 0
    language_stats: dict[str, int] = {}

    for row in users:
        (
            user_id,
            family_id,
            telegram_id,
            user_language,
            preferred_language,
            notification_language,
            timezone,
            timezone_source,
            tone_preference,
            learned_patterns,
        ) = row
        try:
            resolved = resolve_notification_locale(
                user_language=user_language,
                preferred_language=preferred_language,
                notification_language=notification_language,
                timezone=timezone,
                timezone_source=timezone_source,
                use_v2_read=settings.ff_locale_v2_read,
                prefer_user_on_desync=True,
            )
            comm_mode = tone_preference or "receipt"
            suppressed: list[str] = []
            if learned_patterns and isinstance(learned_patterns, dict):
                suppressed = learned_patterns.get("suppressed_triggers", [])

            messages = await run_for_user(
                user_id=str(user_id),
                family_id=str(family_id),
                language=resolved.language,
                communication_mode=comm_mode,
                suppressed_triggers=suppressed,
            )

            for msg in messages:
                await send_telegram_message(telegram_id, msg["message"])
                sent_count += 1
                language_stats[resolved.language] = language_stats.get(resolved.language, 0) + 1
                logger.info(
                    "Proactive sent: trigger=%s telegram_id=%s user_id=%s language=%s "
                    "language_source=%s timezone=%s timezone_source=%s ff_locale_v2_read=%s",
                    msg["trigger"],
                    telegram_id,
                    user_id,
                    resolved.language,
                    resolved.language_source,
                    resolved.timezone,
                    resolved.timezone_source,
                    settings.ff_locale_v2_read,
                )

        except Exception:
            logger.exception("Proactivity failed for user %s", user_id)
    logger.info(
        "Proactivity metrics: sent_total=%d by_language=%s ff_locale_v2_read=%s "
        "ff_reminder_dispatch_v2=%s",
        sent_count,
        language_stats,
        settings.ff_locale_v2_read,
        settings.ff_reminder_dispatch_v2,
    )
