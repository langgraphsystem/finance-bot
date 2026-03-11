"""Conversation analytics sampling and event emission helpers."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from src.core.context import SessionContext
from src.core.release import log_runtime_event
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage

_ACTION_KEYWORDS = (
    "напомни",
    "создай",
    "отправь",
    "покажи",
    "найди",
    "запиши",
    "explain",
    "remind",
    "create",
    "send",
    "show",
    "find",
    "book",
    "schedule",
    "summarize",
    "analyze",
)
_MEMORY_INTENTS = {
    "memory_forget",
    "memory_vault",
    "set_user_rule",
    "set_project",
    "create_project",
}
_ALWAYS_SAMPLE_OUTCOMES = {
    "error",
    "guardrail_blocked",
    "no_reply",
    "rate_limited",
    "tool_failure",
}


def get_conversation_analytics_policy() -> dict[str, Any]:
    """Return the active sampling policy for conversation analytics events."""
    return {
        "always_sample_outcomes": sorted(_ALWAYS_SAMPLE_OUTCOMES),
        "sample_rates": {
            "multi_intent": 30,
            "memory_related": 25,
            "long_input": 2,
            "default_success": 10,
        },
    }


def merge_analytics_tags(*tag_groups: list[str] | tuple[str, ...] | None) -> list[str]:
    """Merge tag groups into a stable, unique list."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in tag_groups:
        if not group:
            continue
        for tag in group:
            if tag and tag not in seen:
                seen.add(tag)
                merged.append(tag)
    return merged


def derive_conversation_tags(
    *,
    message: IncomingMessage,
    intent_name: str | None = None,
    recent_context: str | None = None,
) -> list[str]:
    """Infer analytics tags from the message shape and resolved intent."""
    tags = [f"message_type:{message.type.value}", f"channel:{message.channel}"]
    text = (message.text or "").strip()
    lowered = text.lower()

    if text.startswith("/"):
        tags.append("slash_command")
    if len(text) >= 800:
        tags.append("long_input")
    if recent_context:
        tags.append("context_followup")
    if intent_name in _MEMORY_INTENTS:
        tags.append("memory_related")
    if message.type in {MessageType.photo, MessageType.document}:
        tags.append("media_input")
    if message.type == MessageType.voice:
        tags.append("voice_input")
    if message.type == MessageType.callback:
        tags.append("callback_input")
    if _looks_multi_intent(lowered):
        tags.append("multi_intent")
    return tags


def get_sampling_rule(outcome: str, tags: list[str]) -> dict[str, Any]:
    """Return the sampling rule chosen for the current event."""
    policy = get_conversation_analytics_policy()["sample_rates"]
    tag_set = set(tags)
    if outcome in _ALWAYS_SAMPLE_OUTCOMES:
        return {"sample_percent": 100, "reason": f"outcome:{outcome}"}
    if "multi_intent" in tag_set:
        return {"sample_percent": policy["multi_intent"], "reason": "tag:multi_intent"}
    if "memory_related" in tag_set:
        return {"sample_percent": policy["memory_related"], "reason": "tag:memory_related"}
    if "long_input" in tag_set:
        return {"sample_percent": policy["long_input"], "reason": "tag:long_input"}
    return {"sample_percent": policy["default_success"], "reason": "default:success"}


def should_sample_analytics_event(subject_key: str, sample_percent: int) -> bool:
    """Deterministically sample analytics events."""
    if sample_percent >= 100:
        return True
    if sample_percent <= 0:
        return False
    digest = hashlib.sha256(subject_key.encode()).hexdigest()
    return int(digest[:8], 16) % 100 < sample_percent


def emit_conversation_analytics_event(
    logger: logging.Logger,
    *,
    context: SessionContext | None,
    message: IncomingMessage,
    outcome: str,
    intent_name: str | None = None,
    tags: list[str] | None = None,
    response: OutgoingMessage | None = None,
    extra: dict[str, Any] | None = None,
    force_sample: bool = False,
) -> dict[str, Any] | None:
    """Emit a sampled conversation analytics event to structured logs."""
    merged_tags = merge_analytics_tags(tags)
    sampling = get_sampling_rule(outcome, merged_tags)
    subject_key = (
        f"{context.user_id if context else message.user_id}:{message.id}:{intent_name or 'unknown'}"
    )
    sampled = force_sample or should_sample_analytics_event(
        subject_key,
        sampling["sample_percent"],
    )
    if not sampled:
        return None

    payload = {
        "outcome": outcome,
        "intent": intent_name,
        "tags": merged_tags,
        "sampling_percent": sampling["sample_percent"],
        "sampling_reason": sampling["reason"],
        "response_has_text": bool(response.text) if response else False,
        "response_has_buttons": bool(response.buttons) if response else False,
        "response_length": len(response.text or "") if response else 0,
        "message_length": len(message.text or ""),
    }
    if extra:
        payload.update(extra)

    log_runtime_event(
        logger,
        "info",
        "conversation_analytics_event",
        channel=message.channel,
        chat_id=message.chat_id,
        user_id=context.user_id if context else message.user_id,
        message_id=message.id,
        **payload,
    )
    return payload


def _looks_multi_intent(text: str) -> bool:
    if not text:
        return False
    if not any(marker in text for marker in (" и ", ";", " also ", " then ", " а потом ")):
        return False
    matches = sum(1 for keyword in _ACTION_KEYWORDS if keyword in text)
    return matches >= 2
