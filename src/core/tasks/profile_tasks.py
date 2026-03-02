"""User profile auto-learning — nightly analysis of conversation history.

Updates ``user_profiles.learned_patterns`` with inferred preferences:
- preferred language (based on message language)
- active hours (based on message timestamps)
- common topics
- suppressed triggers
"""

import logging
import re
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

    # Analyze personality traits
    personality = _analyze_personality(messages)

    # Phase 3.1: Observational pattern analysis
    day_of_week_counts = Counter(
        m.created_at.strftime("%A") for m in messages if m.created_at
    )
    hour_distribution = {str(h): c for h, c in hour_counts.items()} if hour_counts else {}
    day_distribution = dict(day_of_week_counts)

    observation_patterns = {
        "hour_distribution": hour_distribution,
        "day_distribution": day_distribution,
        "peak_hours": sorted(hour_counts, key=hour_counts.get, reverse=True)[:3]
        if hour_counts
        else [],
        "peak_days": sorted(
            day_of_week_counts, key=day_of_week_counts.get, reverse=True
        )[:3]
        if day_of_week_counts
        else [],
    }

    # Run Reflector on accumulated observations
    existing_observations: list[str] = []
    try:
        from src.core.memory.observational import (
            load_user_observations,
            restructure_observations,
            save_user_observations,
        )

        existing_observations = await load_user_observations(user_id)
        if existing_observations:
            existing_observations = await restructure_observations(
                existing_observations
            )
            await save_user_observations(user_id, existing_observations)
    except Exception as e:
        logger.debug("Reflector run failed for user %s: %s", user_id, e)

    # Build learned_patterns
    patterns = {
        "active_hours": {"start": active_start, "end": active_end},
        "active_topics": active_topics,
        "message_count_7d": len(messages),
        "last_analyzed": datetime.now(UTC).isoformat(),
        "personality": personality,
        "observation_patterns": observation_patterns,
    }

    # Update user profile
    async with async_session() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == uuid.UUID(user_id))
        )
        profile = result.scalar_one_or_none()

        if profile:
            # Merge with existing patterns (preserve suppressed_triggers + observations)
            existing = profile.learned_patterns or {}
            if "suppressed_triggers" in existing:
                patterns["suppressed_triggers"] = existing["suppressed_triggers"]
            if "observations" in existing:
                patterns["observations"] = existing["observations"]
            if "procedures" in existing:
                patterns["procedures"] = existing["procedures"]
            if "corrections" in existing:
                patterns["corrections"] = existing["corrections"]
            profile.learned_patterns = patterns
            profile.active_hours_start = active_start
            profile.active_hours_end = active_end
            await session.commit()
            logger.info("Updated learned_patterns for user %s", user_id)
        else:
            logger.debug("No user profile for user %s, skipping learning", user_id)


def _analyze_personality(messages: list) -> dict:
    """Analyze user messages to infer communication style.

    Returns a dict for ``learned_patterns["personality"]``.
    """
    if not messages:
        return {}

    texts = [m.content or "" for m in messages]

    # --- Verbosity: average word count per message ---
    word_counts = [len(t.split()) for t in texts]
    avg_words = sum(word_counts) / len(word_counts) if word_counts else 0

    if avg_words > 25:
        verbosity = "detailed"
    elif avg_words < 8:
        verbosity = "concise"
    else:
        verbosity = "moderate"

    # --- Formality: formal vs casual markers ---
    all_text = " ".join(texts).lower()
    formal_markers = [
        "please", "could you", "would you", "kindly",
        "пожалуйста", "будьте добры", "не могли бы", "уважаем",
        "por favor", "podria",
    ]
    casual_markers = [
        "ok", "ок", "ладно", "норм", "давай", "го",
        "lol", "хах", "ахах", "круто", "щас", "ну",
    ]
    formal_count = sum(1 for m in formal_markers if m in all_text)
    casual_count = sum(1 for m in casual_markers if m in all_text)

    if formal_count > casual_count + 2:
        formality = "formal"
    elif casual_count > formal_count + 2:
        formality = "casual"
    else:
        formality = "neutral"

    # --- Emoji usage ---
    emoji_re = re.compile(
        r"[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff"
        r"\U0001f680-\U0001f6ff\U0001f900-\U0001f9ff"
        r"\U00002702-\U000027b0\U0001fa00-\U0001fa6f]"
    )
    emoji_msgs = sum(1 for t in texts if emoji_re.search(t))
    emoji_ratio = emoji_msgs / len(texts) if texts else 0

    if emoji_ratio > 0.5:
        emoji_usage = "heavy"
    elif emoji_ratio > 0.15:
        emoji_usage = "moderate"
    elif emoji_ratio > 0:
        emoji_usage = "light"
    else:
        emoji_usage = "none"

    # --- Language mixing (Latin + Cyrillic in same message) ---
    mixed_count = 0
    for t in texts:
        has_latin = bool(re.search(r"[a-zA-Z]{2,}", t))
        has_cyrillic = bool(re.search(r"[а-яА-ЯёЁ]{2,}", t))
        if has_latin and has_cyrillic:
            mixed_count += 1

    language_mixing = "mixed" if mixed_count > len(texts) * 0.2 else None

    return {
        "verbosity": verbosity,
        "formality": formality,
        "emoji_usage": emoji_usage,
        "language_mixing": language_mixing,
        "avg_message_length": round(avg_words, 1),
        "analyzed_at": datetime.now(UTC).isoformat(),
    }
