"""Conversation analytics sampling and event emission helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
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
_TRACE_INDEX_KEY = "analytics:trace_index"
_REVIEW_RESULT_QUEUE_KEY = "analytics:review_results"
_REVIEW_RESULT_INDEX_KEY = "analytics:review_results:index"
_DATASET_CANDIDATE_QUEUE_KEY = "analytics:dataset_candidates"
_DATASET_CANDIDATE_INDEX_KEY = "analytics:dataset_candidates:index"
_REVIEW_BATCH_QUEUE_KEY = "analytics:review_batches"
_REVIEW_BATCH_INDEX_KEY = "analytics:review_batches:index"
_REVIEW_LABELS = [
    "success",
    "wrong_route",
    "memory_failure",
    "unsafe_block",
    "unsafe_allow",
    "tool_failure",
]
_REVIEW_ACTIONS = [
    "close",
    "follow_up",
    "promote_to_dataset",
]
_REVIEW_RUBRIC_FIELDS = [
    "intent_correct",
    "response_useful",
    "action_completed",
    "clarification_appropriate",
    "memory_applied",
    "safe",
    "language_correct",
    "formatting_correct",
    "latency_acceptable",
]
_MESSAGE_PREVIEW_LIMIT = 500
_RESPONSE_PREVIEW_LIMIT = 1000


def get_conversation_analytics_policy() -> dict[str, Any]:
    """Return the active sampling policy for conversation analytics events."""
    return {
        "always_sample_outcomes": sorted(_ALWAYS_SAMPLE_OUTCOMES),
        "review_labels": list(_REVIEW_LABELS),
        "review_actions": list(_REVIEW_ACTIONS),
        "review_rubric": list(_REVIEW_RUBRIC_FIELDS),
        "review_suggestion_fields": [
            "suggested_final_label",
            "suggested_action",
            "suggested_rubric",
            "suggested_labels",
            "rationale",
        ],
        "review_queue_filter_fields": [
            "review_label",
            "suggested_action",
            "suggested_final_label",
            "tag",
            "source",
        ],
        "sample_rates": {
            "multi_intent": 30,
            "memory_related": 25,
            "long_input": 2,
            "default_success": 10,
        },
        "review_queue_limit": settings.analytics_review_queue_limit,
        "trace_export_queue_limit": settings.analytics_trace_export_queue_limit,
        "review_result_limit": settings.analytics_review_result_limit,
        "dataset_candidate_limit": settings.analytics_dataset_candidate_limit,
        "review_batch_limit": settings.analytics_review_batch_limit,
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


def _normalize_filter_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def filter_review_queue_items(
    items: list[dict[str, Any]],
    *,
    review_label: str | None = None,
    suggested_action: str | None = None,
    suggested_final_label: str | None = None,
    tag: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Filter review-queue items using operator-facing selection criteria."""
    normalized_review_label = _normalize_filter_value(review_label)
    normalized_suggested_action = _normalize_filter_value(suggested_action)
    normalized_suggested_final_label = _normalize_filter_value(suggested_final_label)
    normalized_tag = _normalize_filter_value(tag)
    normalized_source = _normalize_filter_value(source)

    filtered: list[dict[str, Any]] = []
    for item in items:
        if (
            normalized_review_label
            and str(item.get("review_label") or "") != normalized_review_label
        ):
            continue
        suggestion = dict(item.get("review_suggestion") or {})
        if (
            normalized_suggested_action
            and str(suggestion.get("suggested_action") or "") != normalized_suggested_action
        ):
            continue
        if (
            normalized_suggested_final_label
            and str(suggestion.get("suggested_final_label") or "")
            != normalized_suggested_final_label
        ):
            continue
        if normalized_tag and normalized_tag not in {str(tag) for tag in item.get("tags") or []}:
            continue
        if normalized_source and str(item.get("source") or "") != normalized_source:
            continue
        filtered.append(item)
    return filtered


def build_review_queue_selection_summary(
    items: list[dict[str, Any]],
    *,
    max_selected: int = 50,
    review_label: str | None = None,
    suggested_action: str | None = None,
    suggested_final_label: str | None = None,
    tag: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Build a stable trace-key selection from filtered review-queue items."""
    selected_trace_keys: list[str] = []
    seen: set[str] = set()
    for item in items:
        trace_key = str(item.get("trace_key") or "").strip()
        if not trace_key or trace_key in seen:
            continue
        seen.add(trace_key)
        selected_trace_keys.append(trace_key)
        if len(selected_trace_keys) >= max(1, max_selected):
            break

    return {
        "selection_filters": {
            "review_label": _normalize_filter_value(review_label),
            "suggested_action": _normalize_filter_value(suggested_action),
            "suggested_final_label": _normalize_filter_value(suggested_final_label),
            "tag": _normalize_filter_value(tag),
            "source": _normalize_filter_value(source),
        },
        "selected_trace_key_count": len(selected_trace_keys),
        "selected_trace_keys": selected_trace_keys,
    }


def _default_review_rubric() -> dict[str, bool]:
    return {field: True for field in _REVIEW_RUBRIC_FIELDS}


def build_review_suggestion(
    *,
    review_label: str,
    outcome: str,
    tags: list[str] | None = None,
    source: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a prefilled review suggestion for operators."""
    tag_set = set(tags or [])
    metadata = dict(metadata or {})
    rubric = _default_review_rubric()
    suggested_action = "close" if review_label == "success" else "follow_up"
    suggested_labels: list[str] = []
    rationale_parts = [f"outcome={outcome}", f"review_label={review_label}"]

    if review_label == "wrong_route":
        rubric.update(
            {
                "intent_correct": False,
                "response_useful": False,
                "action_completed": False,
                "clarification_appropriate": False,
            }
        )
        suggested_labels.append("routing")
        rationale_parts.append("route mismatch heuristics")
    elif review_label == "memory_failure":
        rubric.update(
            {
                "response_useful": False,
                "action_completed": False,
                "memory_applied": False,
            }
        )
        suggested_labels.append("memory")
        rationale_parts.append("memory-related failure heuristics")
    elif review_label == "tool_failure":
        rubric.update(
            {
                "response_useful": False,
                "action_completed": False,
            }
        )
        suggested_labels.append("tooling")
        rationale_parts.append("tool execution or fallback heuristics")
    elif review_label == "unsafe_block":
        rubric.update(
            {
                "response_useful": False,
                "action_completed": False,
                "clarification_appropriate": False,
            }
        )
        suggested_labels.append("guardrails")
        rationale_parts.append("guardrail block should be reviewed")
    elif review_label == "unsafe_allow":
        rubric.update(
            {
                "response_useful": False,
                "action_completed": False,
                "safe": False,
            }
        )
        suggested_labels.append("guardrails")
        rationale_parts.append("unsafe allow requires safety review")

    if "multi_intent" in tag_set:
        suggested_labels.append("multi_intent")
    if "memory_related" in tag_set and "memory" not in suggested_labels:
        suggested_labels.append("memory")
    if "shadow_mismatch" in tag_set and "routing" not in suggested_labels:
        suggested_labels.append("routing")

    reference_rubric = metadata.get("reference_rubric")
    if isinstance(reference_rubric, dict) and reference_rubric.get("passed") is False:
        rubric["response_useful"] = False
        rubric["action_completed"] = False
        rationale_parts.append(
            f"reference mismatch ({reference_rubric.get('verdict', 'unknown')})"
        )

    is_golden_replay = source == "test_bot_live_golden_replay" or "golden_replay" in tag_set
    if is_golden_replay:
        suggested_labels.append("golden_replay")
        if review_label in {"wrong_route", "memory_failure", "tool_failure"}:
            suggested_action = "promote_to_dataset"
        rationale_parts.append("golden replay failure")
    elif review_label == "success":
        suggested_action = "close"

    return {
        "suggested_final_label": review_label,
        "suggested_action": suggested_action,
        "suggested_rubric": rubric,
        "suggested_labels": sorted(set(suggested_labels)),
        "rationale": "; ".join(rationale_parts),
    }


async def _push_queue_item(key: str, payload: dict[str, Any], *, limit: int) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    await redis.lpush(key, serialized)
    await redis.ltrim(key, 0, max(limit - 1, 0))


async def _store_review_batch_record(payload: dict[str, Any]) -> None:
    """Persist review batch audit records without breaking the main flow."""
    try:
        batch_id = str(payload.get("batch_id") or "")
        if batch_id:
            await redis.hset(
                _REVIEW_BATCH_INDEX_KEY,
                batch_id,
                json.dumps(payload, ensure_ascii=False, default=str),
            )
        await _push_queue_item(
            _REVIEW_BATCH_QUEUE_KEY,
            payload,
            limit=settings.analytics_review_batch_limit,
        )
    except Exception:
        logging.getLogger(__name__).debug("Failed to store review batch record", exc_info=True)


async def _store_trace_artifacts(payload: dict[str, Any]) -> None:
    """Persist analytics exports and review candidates in Redis lists."""
    try:
        trace_key = str(payload.get("trace_key") or "")
        if trace_key:
            await redis.hset(
                _TRACE_INDEX_KEY,
                trace_key,
                json.dumps(payload, ensure_ascii=False, default=str),
            )
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


async def get_trace_by_key(trace_key: str) -> dict[str, Any] | None:
    """Return a stored trace export by its stable trace key."""
    if not trace_key:
        return None
    try:
        item = await redis.hget(_TRACE_INDEX_KEY, trace_key)
    except Exception:
        logging.getLogger(__name__).debug("Failed to fetch trace by key", exc_info=True)
        return None
    if not item:
        return None
    try:
        return json.loads(item)
    except (TypeError, json.JSONDecodeError):
        return None


async def ingest_review_trace(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist an externally supplied trace into exports and the review queue."""
    normalized_trace_key = str(payload.get("trace_key") or "").strip()
    if not normalized_trace_key:
        raise ValueError("trace_key_required")

    tags = merge_analytics_tags(list(payload.get("tags") or []))
    outcome = str(payload.get("outcome") or "error").strip() or "error"
    metadata = dict(payload.get("metadata") or {})
    review_label = normalize_review_label(
        outcome,
        tags,
        {
            "review_label": payload.get("review_label"),
            **metadata,
        },
    )
    message_preview = str(payload.get("message_preview") or "")[:_MESSAGE_PREVIEW_LIMIT]
    response_preview = str(payload.get("response_preview") or "")[:_RESPONSE_PREVIEW_LIMIT]
    response_has_text = payload.get("response_has_text")
    response_length = payload.get("response_length")
    if response_length is None:
        normalized_response_length = len(response_preview)
    else:
        try:
            normalized_response_length = max(0, int(response_length))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_response_length") from exc

    queued_for_review = payload.get("queued_for_review")
    normalized_payload = {
        "trace_key": normalized_trace_key,
        "request_id": str(payload.get("request_id") or normalized_trace_key),
        "correlation_id": str(payload.get("correlation_id") or normalized_trace_key),
        "channel": str(payload.get("channel") or "telegram"),
        "chat_id": str(payload.get("chat_id") or ""),
        "user_id": str(payload.get("user_id") or ""),
        "message_id": str(payload.get("message_id") or ""),
        "intent": str(payload.get("intent") or ""),
        "outcome": outcome,
        "review_label": review_label,
        "tags": tags,
        "message_preview": message_preview,
        "response_preview": response_preview,
        "response_has_text": (
            bool(response_has_text) if response_has_text is not None else bool(response_preview)
        ),
        "response_length": normalized_response_length,
        "queued_for_review": (
            bool(queued_for_review)
            if queued_for_review is not None
            else should_queue_review_candidate(review_label, tags)
        ),
        "source": str(payload.get("source") or "external_trace"),
        "metadata": metadata,
        "captured_at": str(payload.get("captured_at") or datetime.now(UTC).isoformat()),
    }
    normalized_payload["review_suggestion"] = build_review_suggestion(
        review_label=review_label,
        outcome=outcome,
        tags=tags,
        source=normalized_payload["source"],
        metadata=metadata,
    )
    await _store_trace_artifacts(normalized_payload)
    return normalized_payload


def _normalize_review_rubric(rubric: dict[str, Any]) -> dict[str, bool]:
    normalized: dict[str, bool] = {}
    missing = [field for field in _REVIEW_RUBRIC_FIELDS if field not in rubric]
    if missing:
        raise ValueError(f"missing_rubric_fields:{','.join(missing)}")
    for field in _REVIEW_RUBRIC_FIELDS:
        value = rubric[field]
        if not isinstance(value, bool):
            raise ValueError(f"invalid_rubric_value:{field}")
        normalized[field] = value
    return normalized


async def submit_trace_review(
    *,
    trace_key: str,
    reviewer: str,
    final_label: str,
    action: str,
    rubric: dict[str, Any],
    notes: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Persist a structured human review and optionally promote it to dataset candidates."""
    normalized_trace_key = trace_key.strip()
    normalized_reviewer = reviewer.strip()
    if not normalized_trace_key:
        raise ValueError("trace_key_required")
    if not normalized_reviewer:
        raise ValueError("reviewer_required")
    if final_label not in _REVIEW_LABELS:
        raise ValueError("invalid_final_label")
    if action not in _REVIEW_ACTIONS:
        raise ValueError("invalid_review_action")

    rubric_result = _normalize_review_rubric(rubric)
    trace_payload = await get_trace_by_key(normalized_trace_key)
    if not trace_payload:
        raise ValueError("trace_not_found")

    review_payload = {
        "trace_key": normalized_trace_key,
        "reviewer": normalized_reviewer,
        "final_label": final_label,
        "action": action,
        "rubric": rubric_result,
        "notes": notes.strip(),
        "labels": list(labels or []),
        "reviewed_at": datetime.now(UTC).isoformat(),
        "source_review_label": trace_payload.get("review_label"),
        "source_outcome": trace_payload.get("outcome"),
    }
    serialized_review = json.dumps(review_payload, ensure_ascii=False, default=str)
    await redis.hset(_REVIEW_RESULT_INDEX_KEY, normalized_trace_key, serialized_review)
    await _push_queue_item(
        _REVIEW_RESULT_QUEUE_KEY,
        review_payload,
        limit=settings.analytics_review_result_limit,
    )

    dataset_candidate_created = action == "promote_to_dataset"
    if dataset_candidate_created:
        dataset_payload = {
            "trace_key": normalized_trace_key,
            "trace": trace_payload,
            "review": review_payload,
            "candidate_created_at": datetime.now(UTC).isoformat(),
        }
        serialized_candidate = json.dumps(dataset_payload, ensure_ascii=False, default=str)
        await redis.hset(_DATASET_CANDIDATE_INDEX_KEY, normalized_trace_key, serialized_candidate)
        await _push_queue_item(
            _DATASET_CANDIDATE_QUEUE_KEY,
            dataset_payload,
            limit=settings.analytics_dataset_candidate_limit,
        )

    return {
        "review": review_payload,
        "dataset_candidate_created": dataset_candidate_created,
        "trace": trace_payload,
    }


async def apply_trace_review_suggestion(
    *,
    trace_key: str,
    reviewer: str,
    notes: str = "",
    final_label: str | None = None,
    action: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Apply the prefilled review suggestion for a trace with optional overrides."""
    trace_payload = await get_trace_by_key(trace_key.strip())
    if not trace_payload:
        raise ValueError("trace_not_found")

    suggestion = dict(trace_payload.get("review_suggestion") or {})
    if not suggestion:
        raise ValueError("review_suggestion_missing")

    suggested_rubric = dict(suggestion.get("suggested_rubric") or {})
    if not suggested_rubric:
        raise ValueError("review_suggestion_missing_rubric")

    resolved_final_label = str(
        final_label.strip() if final_label else suggestion.get("suggested_final_label") or ""
    )
    resolved_action = str(
        action.strip() if action else suggestion.get("suggested_action") or ""
    )
    merged_labels = list(
        dict.fromkeys(
            list(suggestion.get("suggested_labels") or []) + list(labels or [])
        )
    )
    rationale = str(suggestion.get("rationale") or "").strip()
    combined_notes = "; ".join(part for part in [rationale, notes.strip()] if part)

    return await submit_trace_review(
        trace_key=trace_key,
        reviewer=reviewer,
        final_label=resolved_final_label,
        action=resolved_action,
        rubric=suggested_rubric,
        notes=combined_notes,
        labels=merged_labels,
    )


async def apply_trace_review_suggestions_batch(
    *,
    trace_keys: list[str],
    reviewer: str,
    notes: str = "",
    final_label: str | None = None,
    action: str | None = None,
    labels: list[str] | None = None,
    selection_limit: int = 100,
    review_label: str | None = None,
    suggested_action: str | None = None,
    suggested_final_label: str | None = None,
    tag: str | None = None,
    source: str | None = None,
    max_selected: int = 50,
) -> dict[str, Any]:
    """Apply stored review suggestions for multiple traces and summarize results."""
    normalized_keys: list[str] = []
    seen: set[str] = set()
    for trace_key in trace_keys:
        key = trace_key.strip()
        if key and key not in seen:
            seen.add(key)
            normalized_keys.append(key)
    selection_summary: dict[str, Any] | None = None
    if not normalized_keys:
        queue_items = await get_review_queue(limit=max(1, selection_limit))
        filtered_items = filter_review_queue_items(
            queue_items,
            review_label=review_label,
            suggested_action=suggested_action,
            suggested_final_label=suggested_final_label,
            tag=tag,
            source=source,
        )
        selection_summary = build_review_queue_selection_summary(
            filtered_items,
            max_selected=max_selected,
            review_label=review_label,
            suggested_action=suggested_action,
            suggested_final_label=suggested_final_label,
            tag=tag,
            source=source,
        )
        normalized_keys = list(selection_summary["selected_trace_keys"])
    if not normalized_keys:
        raise ValueError("trace_keys_required")

    applied: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for trace_key in normalized_keys:
        try:
            result = await apply_trace_review_suggestion(
                trace_key=trace_key,
                reviewer=reviewer,
                notes=notes,
                final_label=final_label,
                action=action,
                labels=labels,
            )
            applied.append(
                {
                    "trace_key": trace_key,
                    "dataset_candidate_created": result["dataset_candidate_created"],
                    "review": result["review"],
                }
            )
        except ValueError as exc:
            failed.append({"trace_key": trace_key, "error": str(exc)})

    batch_result = {
        "batch_id": f"review-batch:{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
        "reviewer": reviewer,
        "requested": len(normalized_keys),
        "applied_count": len(applied),
        "failed_count": len(failed),
        "applied": applied,
        "failed": failed,
        "selection": selection_summary,
        "notes": notes.strip(),
        "labels": list(labels or []),
        "final_label_override": final_label,
        "action_override": action,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await _store_review_batch_record(batch_result)
    return batch_result


async def get_review_batches(limit: int = 25) -> list[dict[str, Any]]:
    """Return recent batch review operations for operator audit/history."""
    try:
        items = await redis.lrange(_REVIEW_BATCH_QUEUE_KEY, 0, max(limit - 1, 0))
    except Exception:
        logging.getLogger(__name__).debug("Failed to fetch review batches", exc_info=True)
        return []
    parsed: list[dict[str, Any]] = []
    for item in items:
        try:
            parsed.append(json.loads(item))
        except (TypeError, json.JSONDecodeError):
            continue
    return parsed


async def get_dataset_candidates(limit: int = 25) -> list[dict[str, Any]]:
    """Return recent reviewed traces promoted to dataset candidates."""
    try:
        items = await redis.lrange(_DATASET_CANDIDATE_QUEUE_KEY, 0, max(limit - 1, 0))
    except Exception:
        logging.getLogger(__name__).debug("Failed to fetch dataset candidates", exc_info=True)
        return []
    parsed: list[dict[str, Any]] = []
    for item in items:
        try:
            parsed.append(json.loads(item))
        except (TypeError, json.JSONDecodeError):
            continue
    return parsed


async def get_review_results(limit: int = 25) -> list[dict[str, Any]]:
    """Return recent structured review results."""
    try:
        items = await redis.lrange(_REVIEW_RESULT_QUEUE_KEY, 0, max(limit - 1, 0))
    except Exception:
        logging.getLogger(__name__).debug("Failed to fetch review results", exc_info=True)
        return []
    parsed: list[dict[str, Any]] = []
    for item in items:
        try:
            parsed.append(json.loads(item))
        except (TypeError, json.JSONDecodeError):
            continue
    return parsed


def _build_golden_dialogue(candidate: dict[str, Any]) -> dict[str, Any]:
    trace = candidate.get("trace") or {}
    review = candidate.get("review") or {}
    tags = list(trace.get("tags") or [])
    scenario = (
        "multi_intent"
        if "multi_intent" in tags
        else "memory"
        if "memory_related" in tags
        else "guardrails"
        if review.get("final_label") in {"unsafe_block", "unsafe_allow"}
        else "general"
    )
    return {
        "id": candidate.get("trace_key"),
        "trace_key": candidate.get("trace_key"),
        "scenario": scenario,
        "source": "production_review",
        "channel": trace.get("channel"),
        "intent": trace.get("intent"),
        "review_label": review.get("final_label"),
        "labels": list(review.get("labels") or []),
        "input_text": trace.get("message_preview", ""),
        "assistant_response": trace.get("response_preview", ""),
        "review_notes": review.get("notes", ""),
        "rubric": review.get("rubric", {}),
        "metadata": {
            "tags": tags,
            "source_outcome": review.get("source_outcome"),
            "source_review_label": review.get("source_review_label"),
            "reviewed_at": review.get("reviewed_at"),
            "candidate_created_at": candidate.get("candidate_created_at"),
        },
    }


async def get_golden_dialogues(limit: int = 25) -> list[dict[str, Any]]:
    """Return dataset candidates transformed into a golden-dialogue export format."""
    candidates = await get_dataset_candidates(limit=limit)
    return [_build_golden_dialogue(candidate) for candidate in candidates]


async def get_weekly_curation_snapshot(limit: int = 25) -> dict[str, Any]:
    """Return a compact operator snapshot for weekly trace-to-dataset curation."""
    review_results = await get_review_results(limit=limit)
    dataset_candidates = await get_dataset_candidates(limit=limit)
    review_batches = await get_review_batches(limit=limit)
    label_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for review in review_results:
        label = str(review.get("final_label") or "unknown")
        action = str(review.get("action") or "unknown")
        label_counts[label] = label_counts.get(label, 0) + 1
        action_counts[action] = action_counts.get(action, 0) + 1
    return {
        "policy": get_conversation_analytics_policy(),
        "review_result_size": len(review_results),
        "dataset_candidate_size": len(dataset_candidates),
        "review_batch_size": len(review_batches),
        "review_label_counts": label_counts,
        "review_action_counts": action_counts,
        "recent_reviews": review_results,
        "recent_review_batches": review_batches,
        "golden_dialogues": [_build_golden_dialogue(candidate) for candidate in dataset_candidates],
    }


async def get_review_queue_snapshot(
    limit: int = 25,
    *,
    review_label: str | None = None,
    suggested_action: str | None = None,
    suggested_final_label: str | None = None,
    tag: str | None = None,
    source: str | None = None,
    max_selected: int = 50,
) -> dict[str, Any]:
    """Return a compact operator snapshot of review candidates and trace exports."""
    review_items = await get_review_queue(limit=limit)
    filtered_review_items = filter_review_queue_items(
        review_items,
        review_label=review_label,
        suggested_action=suggested_action,
        suggested_final_label=suggested_final_label,
        tag=tag,
        source=source,
    )
    trace_exports = await get_trace_exports(limit=limit)
    selection = build_review_queue_selection_summary(
        filtered_review_items,
        max_selected=max_selected,
        review_label=review_label,
        suggested_action=suggested_action,
        suggested_final_label=suggested_final_label,
        tag=tag,
        source=source,
    )
    return {
        "policy": get_conversation_analytics_policy(),
        "review_queue_size": len(review_items),
        "filtered_review_queue_size": len(filtered_review_items),
        "trace_export_size": len(trace_exports),
        "review_queue": filtered_review_items,
        "trace_exports": trace_exports,
        **selection,
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
    metadata = (
        dict(extra.get("metadata") or {})
        if isinstance(extra, dict)
        else {}
    )
    source = (
        str(extra.get("source") or "runtime_event")
        if isinstance(extra, dict)
        else "runtime_event"
    )
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
        "message_preview": (message.text or "")[:_MESSAGE_PREVIEW_LIMIT],
        "response_preview": (response.text or "")[:_RESPONSE_PREVIEW_LIMIT] if response else "",
        "source": source,
        "metadata": metadata,
    }
    if extra:
        payload.update(extra)
    payload["queued_for_review"] = should_queue_review_candidate(review_label, merged_tags)
    payload["review_suggestion"] = build_review_suggestion(
        review_label=review_label,
        outcome=outcome,
        tags=merged_tags,
        source=str(payload.get("source") or source),
        metadata=dict(payload.get("metadata") or {}),
    )

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
