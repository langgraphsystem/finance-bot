"""User profile auto-learning — nightly analysis of conversation history.

Updates ``user_profiles.learned_patterns`` with inferred preferences:
- preferred language (based on message language)
- active hours (based on message timestamps)
- common topics
- suppressed triggers
"""

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.conversation import ConversationMessage
from src.core.models.enums import MessageRole
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)

# Minimum messages to start learning
MIN_MESSAGES_FOR_LEARNING = 10


@broker.task(schedule=[{"cron": "0 3 * * *"}])
async def update_user_profiles():
    """Daily at 3am: analyze recent messages and update learned_patterns."""
    async with async_session() as session:
        result = await session.execute(select(User.id, User.family_id))
        users = result.all()

    for user_id, family_id in users:
        try:
            await _learn_for_user(str(user_id), str(family_id))
        except Exception:
            logger.exception("Profile learning failed for user %s", user_id)


async def _learn_for_user(user_id: str, family_id: str) -> None:
    """Analyze last 50 messages and update learned_patterns."""
    import uuid

    cutoff = datetime.now(UTC) - timedelta(days=7)

    async with async_session() as session:
        result = await session.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.user_id == uuid.UUID(user_id),
                ConversationMessage.role == MessageRole.user,
                ConversationMessage.created_at >= cutoff,
            )
            .order_by(ConversationMessage.created_at.desc())
            .limit(50)
        )
        messages = list(result.scalars().all())

    if len(messages) < MIN_MESSAGES_FOR_LEARNING:
        return

    # Analyze active hours
    hour_counts = Counter(m.created_at.hour for m in messages if m.created_at)
    if hour_counts:
        sorted_hours = sorted(hour_counts.keys())
        active_start = sorted_hours[0]
        active_end = sorted_hours[-1]
    else:
        active_start, active_end = 8, 22

    # Analyze common words for topic detection
    all_text = " ".join(m.content or "" for m in messages).lower()
    topic_signals = {
        "finance": any(w in all_text for w in ["spend", "budget", "expense", "invoice", "cost"]),
        "calendar": any(w in all_text for w in ["schedule", "meeting", "appointment", "calendar"]),
        "tasks": any(w in all_text for w in ["task", "remind", "todo", "deadline"]),
        "email": any(w in all_text for w in ["email", "inbox", "mail", "send"]),
    }
    active_topics = [t for t, active in topic_signals.items() if active]

    # Build learned_patterns
    patterns = {
        "active_hours": {"start": active_start, "end": active_end},
        "active_topics": active_topics,
        "message_count_7d": len(messages),
        "last_analyzed": datetime.now(UTC).isoformat(),
    }

    # Update user profile
    async with async_session() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == uuid.UUID(user_id))
        )
        profile = result.scalar_one_or_none()

        if profile:
            # Merge with existing patterns (preserve suppressed_triggers)
            existing = profile.learned_patterns or {}
            if "suppressed_triggers" in existing:
                patterns["suppressed_triggers"] = existing["suppressed_triggers"]
            profile.learned_patterns = patterns
            profile.active_hours_start = active_start
            profile.active_hours_end = active_end
            await session.commit()
            logger.info("Updated learned_patterns for user %s", user_id)
        else:
            logger.debug("No user profile for user %s, skipping learning", user_id)
