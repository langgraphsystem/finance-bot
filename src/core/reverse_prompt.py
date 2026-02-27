"""Reverse prompting — propose a plan before executing complex requests."""

import json
import logging

from src.core.context import SessionContext
from src.core.db import redis

logger = logging.getLogger(__name__)

REVERSE_PROMPT_TTL = 600  # 10 minutes

# Pattern C skills (direct DB write, no LLM) — never trigger reverse prompting
SKIP_REVERSE_INTENTS: set[str] = {
    "add_expense",
    "add_income",
    "track_food",
    "track_drink",
    "mood_checkin",
    "quick_capture",
    "set_comm_mode",
    "complete_task",
    "shopping_list_add",
    "shopping_list_remove",
    "shopping_list_clear",
    "mark_paid",
    "undo_last",
    "correct_category",
    "scan_receipt",
    "scan_document",
    "onboarding",
    "general_chat",
    "memory_show",
    "memory_forget",
    "memory_save",
}

# Multi-step keywords (EN / RU / ES)
MULTI_STEP_KEYWORDS: list[str] = [
    "and then",
    "after that",
    "also",
    "plus ",
    "а потом",
    "после этого",
    "а также",
    "и ещё",
    "и еще",
    "затем",
    "плюс ",
    "y luego",
    "después",
    "también",
    "además",
]

# "Just do it" bypass keywords
BYPASS_KEYWORDS: list[str] = [
    "just do it",
    "просто сделай",
    "делай",
    "go ahead",
    "hazlo",
    "execute",
    "выполняй",
    "не спрашивай",
]


def should_reverse_prompt(
    text: str,
    intent: str,
    confidence: float,
) -> bool:
    """Decide whether to show a plan proposal before executing.

    Returns True if the request is complex enough to warrant a plan.
    """
    if not text:
        return False

    if intent in SKIP_REVERSE_INTENTS:
        return False

    text_lower = text.lower()
    if any(kw in text_lower for kw in BYPASS_KEYWORDS):
        return False

    word_count = len(text.split())

    # Trigger 1: long message (>50 words)
    if word_count > 50:
        return True

    # Trigger 2: medium confidence with moderate length
    if 0.6 <= confidence <= 0.8 and word_count > 15:
        return True

    # Trigger 3: multi-step keywords
    if any(kw in text_lower for kw in MULTI_STEP_KEYWORDS):
        return True

    return False


async def generate_plan_proposal(
    text: str,
    intent: str,
    context: SessionContext,
) -> str:
    """Generate a short plan proposal (3-5 steps) using a lightweight LLM call."""
    from src.core.llm.clients import generate_text

    lang = context.language or "en"
    system = (
        f"You are a planning assistant. The user sent a request. "
        f"Propose a short execution plan (3-5 numbered steps) in {lang}. "
        f"Each step is one short sentence. Do NOT execute. Just list the steps."
    )

    plan_text = await generate_text(
        model="gemini-3-flash-preview",
        system=system,
        prompt=f"User request: {text}\nDetected intent: {intent}",
        max_tokens=512,
    )
    return plan_text


async def store_pending_plan(
    user_id: str,
    intent: str,
    original_text: str,
    intent_data: dict,
    plan_text: str,
) -> None:
    """Store the proposed plan in Redis."""
    payload = {
        "intent": intent,
        "original_text": original_text,
        "intent_data": {
            k: v
            for k, v in intent_data.items()
            if v is not None and k not in ("_assembled", "_agent", "_model")
        },
        "plan_text": plan_text,
    }
    key = f"plan_pending:{user_id}"
    await redis.set(key, json.dumps(payload, default=str), ex=REVERSE_PROMPT_TTL)


async def get_pending_plan(user_id: str) -> dict | None:
    """Retrieve a pending plan from Redis."""
    key = f"plan_pending:{user_id}"
    raw = await redis.get(key)
    if not raw:
        return None
    return json.loads(raw)


async def delete_pending_plan(user_id: str) -> None:
    """Delete a pending plan from Redis."""
    key = f"plan_pending:{user_id}"
    await redis.delete(key)
