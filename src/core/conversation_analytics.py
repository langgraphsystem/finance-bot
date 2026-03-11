"""Conversation analytics sampling and event emission helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from src.core.config import settings
from src.core.context import SessionContext
from src.core.db import redis
from src.core.release import log_runtime_event
from src.core.request_context import (
    get_current_correlation_id,
    get_current_request_id,
)
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
_REVIEW_QUEUE_KEY = "analytics:review_queue"
_TRACE_EXPORT_QUEUE_KEY = "analytics:trace_exports"


def get_conversation_analytics_policy() -> dict[str, Any]:
    """Return the active sampling policy for conversation analytics events."""
    return {
        "always_sample_outcomes": sorted(_ALWAYS_SAMPLE_OUTCOMES),
        "review_labels": [
            "success",
            "wrong_route",
            "memory_failure",
            "unsafe_block",
            "unsafe_allow",
            "tool_failure",
        ],
        "sample_rates": {
            "multi_intent": 30,
            "memory_related": 25,
            "long_input": 2,
            "default_success": 10,
        },
        "review_queue_limit": settings.analytics_review_queue_limit,
        "trace_export_queue_limit": settings.analytics_trace_export_queue_limit,
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


def normalize_review_label(
    outcome: str,
    tags: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Map runtime outcome/tags to a review queue label."""
    if extra and extra.get("review_label"):
        return str(extra["review_label"])

    tag_set = set(tags or [])
    if outcome == "success":
        return "success"
    if outcome == "guardrail_blocked":
        return "unsafe_block"
    if outcome == "unsafe_allow":
        return "unsafe_allow"
    if outcome == "wrong_route" or "shadow_mismatch" in tag_set:
        return "wrong_route"
    if "memory_related" in tag_set and outcome in {"error", "no_reply", "memory_failure"}:
        return "memory_failure"
    return "tool_failure"


def should_queue_review_candidate(review_label: str, tags: list[str] | None = None) -> bool:
    """Decide whether the event should be placed into the manual review queue."""
    if review_label != "success":
        return True
    tag_set = set(tags or [])
    return "multi_intent" in tag_set or "memory_related" in tag_set


async def _push_queue_item(key: str, payload: dict[str, Any], *, limit: int) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    await redis.lpush(key, serialized)
    await redis.ltrim(key, 0, max(limit - 1, 0))


async def _store_trace_artifacts(payload: dict[str, Any]) -> None:
    """Persist analytics exports and review candidates in Redis lists."""
    try:
        await _push_queue_item(
            _TRACE_EXPORT_QUEUE_KEY,
            payload,
            limit=settings.analytics_trace_export_queue_limit,
        )
        if payload.get("queued_for_review"):
            await _push_queue_item(
                _REVIEW_QUEUE_KEY,
                payload,
                limit=settings.analytics_review_queue_limit,
            )
    except Exception:
        logging.getLogger(__name__).debug("Failed to store analytics artifact", exc_info=True)


def schedule_review_trace_capture(payload: dict[str, Any]) -> None:
    """Schedule Redis-backed trace export without blocking the request."""
    current_request_id = get_current_request_id()
    current_correlation_id = get_current_correlation_id()
    enriched_payload = {
        **payload,
        "request_id": payload.get("request_id") or current_request_id,
        "correlation_id": payload.get("correlation_id") or current_correlation_id,
        "trace_key": (
            payload.get("trace_key")
            or current_correlation_id
            or current_request_id
        ),
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_store_trace_artifacts(enriched_payload))


async def get_review_queue(limit: int = 25) -> list[dict[str, Any]]:
    """Return recent review candidates."""
    try:
        items = await redis.lrange(_REVIEW_QUEUE_KEY, 0, max(limit - 1, 0))
    except Exception:
        logging.getLogger(__name__).debug("Failed to fetch review queue", exc_info=True)
        return []
    parsed: list[dict[str, Any]] = []
    for item in items:
        try:
            parsed.append(json.loads(item))
        except (TypeError, json.JSONDecodeError):
            continue
    return parsed


async def get_trace_exports(limit: int = 25) -> list[dict[str, Any]]:
    """Return recent exported analytics traces."""
    try:
        items = await redis.lrange(_TRACE_EXPORT_QUEUE_KEY, 0, max(limit - 1, 0))
    except Exception:
        logging.getLogger(__name__).debug("Failed to fetch trace exports", exc_info=True)
        return []
    parsed: list[dict[str, Any]] = []
    for item in items:
        try:
            parsed.append(json.loads(item))
        except (TypeError, json.JSONDecodeError):
            continue
    return parsed


async def get_review_queue_snapshot(limit: int = 25) -> dict[str, Any]:
    """Return a compact operator snapshot of review candidates and trace exports."""
    review_items = await get_review_queue(limit=limit)
    trace_exports = await get_trace_exports(limit=limit)
    return {
        "policy": get_conversation_analytics_policy(),
        "review_queue_size": len(review_items),
        "trace_export_size": len(trace_exports),
        "review_queue": review_items,
        "trace_exports": trace_exports,
    }


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
    review_label = normalize_review_label(outcome, merged_tags, extra)
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
        "review_label": review_label,
        "tags": merged_tags,
        "sampling_percent": sampling["sample_percent"],
        "sampling_reason": sampling["reason"],
        "request_id": get_current_request_id(),
        "correlation_id": get_current_correlation_id(),
        "trace_key": get_current_correlation_id() or get_current_request_id(),
        "response_has_text": bool(response.text) if response else False,
        "response_has_buttons": bool(response.buttons) if response else False,
        "response_length": len(response.text or "") if response else 0,
        "message_length": len(message.text or ""),
    }
    if extra:
        payload.update(extra)
    payload["queued_for_review"] = should_queue_review_candidate(review_label, merged_tags)

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
    schedule_review_trace_capture(
        {
            "channel": message.channel,
            "chat_id": message.chat_id,
            "user_id": context.user_id if context else message.user_id,
            "message_id": message.id,
            **payload,
        }
    )
    return payload


def _looks_multi_intent(text: str) -> bool:
    if not text:
        return False
    if not any(marker in text for marker in (" и ", ";", " also ", " then ", " а потом ")):
        return False
    matches = sum(1 for keyword in _ACTION_KEYWORDS if keyword in text)
    return matches >= 2
