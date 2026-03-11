import logging
import uuid
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.conversation_analytics import (
    derive_conversation_tags,
    emit_conversation_analytics_event,
    get_conversation_analytics_policy,
    get_review_queue_snapshot,
    get_sampling_rule,
    normalize_review_label,
    schedule_review_trace_capture,
    should_sample_analytics_event,
)
from src.gateway.types import IncomingMessage, MessageType, OutgoingMessage


def _context() -> SessionContext:
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type=None,
        categories=[],
        merchant_mappings=[],
    )


def test_sampling_policy_force_samples_errors():
    rule = get_sampling_rule("error", ["handler_exception"])
    assert rule["sample_percent"] == 100
    assert rule["reason"] == "outcome:error"


def test_derive_tags_marks_multi_intent_and_memory():
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="Напомни про аренду и покажи мои задачи",
    )
    tags = derive_conversation_tags(
        message=msg,
        intent_name="memory_vault",
        recent_context="User: reminder",
    )
    assert "multi_intent" in tags
    assert "memory_related" in tags
    assert "context_followup" in tags


def test_should_sample_analytics_event_is_deterministic():
    first = should_sample_analytics_event("user-1:msg-1:intent", 10)
    second = should_sample_analytics_event("user-1:msg-1:intent", 10)
    assert first is second


def test_emit_conversation_analytics_event_logs_sampled_payload():
    msg = IncomingMessage(
        id="1",
        user_id="u1",
        chat_id="c1",
        type=MessageType.text,
        text="Привет",
    )
    response = OutgoingMessage(text="Здравствуйте", chat_id="c1")
    with patch("src.core.conversation_analytics.log_runtime_event") as mock_log:
        payload = emit_conversation_analytics_event(
            logger=logging.getLogger(__name__),
            context=_context(),
            message=msg,
            outcome="error",
            intent_name="general_chat",
            tags=["handler_exception"],
            response=response,
            force_sample=True,
        )

    assert payload is not None
    assert payload["outcome"] == "error"
    assert payload["sampling_percent"] == 100
    assert mock_log.call_args.args[2] == "conversation_analytics_event"


def test_policy_exposes_sample_rates():
    policy = get_conversation_analytics_policy()
    assert "sample_rates" in policy
    assert policy["sample_rates"]["default_success"] == 10


def test_normalize_review_label_maps_memory_and_guardrails():
    assert normalize_review_label("guardrail_blocked", ["safety"]) == "unsafe_block"
    assert normalize_review_label("error", ["memory_related"]) == "memory_failure"
    assert normalize_review_label("wrong_route", ["shadow_mismatch"]) == "wrong_route"


async def test_get_review_queue_snapshot_returns_review_and_trace_items():
    items = [
        '{"review_label":"wrong_route","queued_for_review":true}',
        '{"review_label":"tool_failure","queued_for_review":true}',
    ]
    with patch("src.core.conversation_analytics.redis") as mock_redis:
        mock_redis.lrange = AsyncMock(side_effect=[items, items])
        snapshot = await get_review_queue_snapshot(limit=2)

    assert snapshot["review_queue_size"] == 2
    assert snapshot["trace_export_size"] == 2
    assert snapshot["review_queue"][0]["review_label"] == "wrong_route"


def test_schedule_review_trace_capture_is_safe_without_loop():
    schedule_review_trace_capture({"review_label": "tool_failure"})


def test_schedule_review_trace_capture_backfills_runtime_context():
    class _Loop:
        def create_task(self, coroutine):
            coroutine.close()

    with (
        patch(
            "src.core.conversation_analytics.get_current_request_id",
            return_value="req-123",
        ),
        patch(
            "src.core.conversation_analytics.get_current_correlation_id",
            return_value="corr-123",
        ),
        patch("src.core.conversation_analytics.asyncio.get_running_loop", return_value=_Loop()),
        patch(
            "src.core.conversation_analytics._store_trace_artifacts",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        schedule_review_trace_capture(
            {
                "review_label": "wrong_route",
                "request_id": None,
                "correlation_id": None,
                "trace_key": None,
            }
        )

    payload = mock_store.call_args.args[0]
    assert payload["request_id"] == "req-123"
    assert payload["correlation_id"] == "corr-123"
    assert payload["trace_key"] == "corr-123"
