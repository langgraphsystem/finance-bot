"""Smart suggestions — contextual next-action buttons after skill execution."""

import logging

from src.core.db import redis

logger = logging.getLogger(__name__)

SUGGESTION_COOLDOWN = 300  # 5 minutes between suggestion sets per user

SUGGESTION_MAP: dict[str, list[dict]] = {
    "add_expense": [
        {"text": "Check budget", "callback": "suggest:query_stats"},
        {"text": "Recent expenses", "callback": "suggest:query_stats:recent"},
    ],
    "add_income": [
        {"text": "Monthly summary", "callback": "suggest:financial_summary"},
    ],
    "create_task": [
        {"text": "All tasks", "callback": "suggest:list_tasks"},
    ],
    "track_food": [
        {"text": "Today's log", "callback": "suggest:life_search:today"},
    ],
    "track_drink": [
        {"text": "Today's log", "callback": "suggest:life_search:today"},
    ],
    "scan_receipt": [
        {"text": "Category breakdown", "callback": "suggest:query_stats"},
    ],
    "complete_task": [
        {"text": "Remaining tasks", "callback": "suggest:list_tasks"},
    ],
    "mood_checkin": [
        {"text": "Week mood trend", "callback": "suggest:life_search:mood_week"},
    ],
    "set_reminder": [
        {"text": "All tasks", "callback": "suggest:list_tasks"},
    ],
    "send_email": [
        {"text": "Inbox", "callback": "suggest:read_inbox"},
    ],
    "create_event": [
        {"text": "Today's schedule", "callback": "suggest:list_events"},
    ],
}


async def get_suggestions(intent: str, user_id: str) -> list[dict] | None:
    """Return contextual suggestion buttons, or None if on cooldown / no mapping."""
    suggestions = SUGGESTION_MAP.get(intent)
    if not suggestions:
        return None

    # Rate limit: max 1 suggestion set per SUGGESTION_COOLDOWN per user
    cooldown_key = f"suggest_shown:{user_id}"
    already_shown = await redis.get(cooldown_key)
    if already_shown:
        return None

    await redis.set(cooldown_key, "1", ex=SUGGESTION_COOLDOWN)
    return suggestions
