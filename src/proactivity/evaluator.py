"""Evaluator — checks all data triggers for a user. No LLM calls.

The evaluator iterates through all registered DataTriggers, collects
any that fired, and returns the raw data for the engine to format.
"""

import logging
from typing import Any

from src.proactivity.triggers import DATA_TRIGGERS

logger = logging.getLogger(__name__)

# Max proactive messages per user per day
MAX_DAILY_PROACTIVE = 5


async def evaluate_triggers(
    user_id: str, family_id: str
) -> list[dict[str, Any]]:
    """Evaluate all data triggers for a user.

    Returns a list of fired triggers with their data::

        [{"name": "task_deadline", "action": "deadline_warning", "data": {...}}, ...]
    """
    fired: list[dict[str, Any]] = []

    for trigger in DATA_TRIGGERS:
        try:
            data = await trigger.check(user_id, family_id)
            if data:
                fired.append({
                    "name": trigger.name,
                    "action": trigger.action,
                    "data": data,
                })
        except Exception:
            logger.exception("Trigger %s failed for user %s", trigger.name, user_id)

    return fired
