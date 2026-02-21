"""Proactivity engine — evaluates triggers and delivers formatted notifications.

Flow:
1. Evaluator checks all data triggers (no LLM).
2. Engine formats fired triggers into user-facing messages (uses LLM).
3. Engine delivers via the appropriate channel.

The engine respects:
- Max 5 proactive messages per user per day.
- User's communication mode (silent = skip all except critical budget alerts).
- User's suppression preferences in learned_patterns.
- Per-trigger cooldown via Redis to prevent spamming the same notification.
"""

import logging
from typing import Any

from src.core.db import redis
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.proactivity.evaluator import MAX_DAILY_PROACTIVE, evaluate_triggers

logger = logging.getLogger(__name__)

# Cooldown in seconds per trigger type — prevents sending the same notification repeatedly
TRIGGER_COOLDOWN: dict[str, int] = {
    "task_deadline": 4 * 3600,      # 4 hours
    "budget_alert": 24 * 3600,      # 24 hours
    "overdue_invoice": 24 * 3600,   # 24 hours
}
DEFAULT_COOLDOWN = 4 * 3600  # 4 hours for unknown triggers

PROACTIVE_SYSTEM_PROMPT = """\
You generate short proactive notification messages for a personal AI assistant.

Rules:
- Lead with the most important item.
- Be scannable — short lines, not paragraphs.
- End with one actionable question or suggestion.
- Max 4 sentences total.
- Use HTML tags for Telegram (<b>, <i>). No Markdown.
- Respond in: {language}.
"""


async def run_for_user(
    user_id: str,
    family_id: str,
    language: str = "en",
    communication_mode: str = "receipt",
    suppressed_triggers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate triggers and generate messages for one user.

    Returns a list of dicts: [{"action": str, "message": str}, ...]
    """
    suppressed = set(suppressed_triggers or [])

    # Skip all proactive messages for silent users (except critical budget alerts)
    if communication_mode == "silent":
        suppressed = suppressed | {
            "task_deadline",
            "overdue_invoice",
            "morning_brief",
            "evening_recap",
        }

    fired = await evaluate_triggers(user_id, family_id)

    # Filter suppressed
    active = [t for t in fired if t["name"] not in suppressed]

    # Filter by cooldown — skip triggers sent recently
    cooled: list[dict[str, Any]] = []
    for t in active:
        cooldown_key = f"proactive:{user_id}:{t['name']}"
        if await redis.exists(cooldown_key):
            logger.debug("Trigger %s for user %s still in cooldown", t["name"], user_id)
            continue
        cooled.append(t)

    # Cap at max daily
    cooled = cooled[:MAX_DAILY_PROACTIVE]

    if not cooled:
        return []

    # Generate messages for each fired trigger
    messages: list[dict[str, Any]] = []
    for trigger_data in cooled:
        try:
            msg = await _format_trigger(trigger_data, language)
            if msg:
                messages.append(
                    {
                        "action": trigger_data["action"],
                        "trigger": trigger_data["name"],
                        "message": msg,
                    }
                )
                # Set cooldown after successful send
                ttl = TRIGGER_COOLDOWN.get(trigger_data["name"], DEFAULT_COOLDOWN)
                cooldown_key = f"proactive:{user_id}:{trigger_data['name']}"
                await redis.set(cooldown_key, "1", ex=ttl)
        except Exception:
            logger.exception(
                "Failed to format trigger %s for user %s",
                trigger_data["name"],
                user_id,
            )

    return messages


async def _format_trigger(trigger_data: dict[str, Any], language: str) -> str:
    """Format a single fired trigger into a user-facing message."""
    name = trigger_data["name"]
    data = trigger_data["data"]

    # Simple triggers — format without LLM
    if name == "task_deadline":
        tasks = data.get("tasks", [])
        lines = ["<b>Upcoming deadlines:</b>"]
        for t in tasks:
            lines.append(f"- {t['title']} (due {t['due_at'][:16]})")
        lines.append("\nWant me to reschedule any of these?")
        return "\n".join(lines)

    if name == "budget_alert":
        pct = data.get("ratio_pct", 0)
        spent = data.get("total_spent", 0)
        budget = data.get("total_budget", 0)
        return (
            f"<b>Budget alert:</b> You've spent ${spent:.0f} of your "
            f"${budget:.0f} monthly budget ({pct}%).\n"
            f"Want to see a breakdown by category?"
        )

    if name == "overdue_invoice":
        overdue = data.get("overdue", [])
        total = sum(o["amount"] for o in overdue)
        return (
            f"<b>{len(overdue)} overdue payment(s)</b> totaling ${total:.0f}.\n"
            f"Want me to list them?"
        )

    # Fallback: use LLM for unknown trigger types
    client = anthropic_client()
    system = PROACTIVE_SYSTEM_PROMPT.format(language=language)
    user_content = f"Trigger: {name}\nData: {data}"
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    response = await client.messages.create(model="claude-haiku-4-5", max_tokens=200, **prompt_data)
    return response.content[0].text
