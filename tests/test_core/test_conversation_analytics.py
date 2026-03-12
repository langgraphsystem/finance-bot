import json
import logging
import uuid
from unittest.mock import AsyncMock, patch

from src.core.context import SessionContext
from src.core.conversation_analytics import (
    apply_trace_review_suggestion,
    build_review_suggestion,
    derive_conversation_tags,
    emit_conversation_analytics_event,
    get_conversation_analytics_policy,
    get_dataset_candidates,
    get_golden_dialogues,
    get_review_queue_snapshot,
    get_review_results,
    get_sampling_rule,
    get_weekly_curation_snapshot,
    ingest_review_trace,
    normalize_review_label,
    schedule_review_trace_capture,
    should_sample_analytics_event,
    submit_trace_review,
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
    assert payload["message_preview"] == "Привет"
    assert payload["response_preview"] == "Здравствуйте"
    assert payload["review_suggestion"]["suggested_final_label"] == "tool_failure"
    assert mock_log.call_args.args[2] == "conversation_analytics_event"


def test_policy_exposes_sample_rates():
    policy = get_conversation_analytics_policy()
    assert "sample_rates" in policy
    assert policy["sample_rates"]["default_success"] == 10
    assert "review_rubric" in policy
    assert "review_suggestion_fields" in policy
    assert "promote_to_dataset" in policy["review_actions"]


def test_normalize_review_label_maps_memory_and_guardrails():
    assert normalize_review_label("guardrail_blocked", ["safety"]) == "unsafe_block"
    assert normalize_review_label("error", ["memory_related"]) == "memory_failure"
    assert normalize_review_label("wrong_route", ["shadow_mismatch"]) == "wrong_route"


def test_build_review_suggestion_prefills_golden_replay_failure():
    suggestion = build_review_suggestion(
        review_label="memory_failure",
        outcome="wrong_route",
        tags=["golden_replay", "memory_related"],
        source="test_bot_live_golden_replay",
        metadata={"reference_rubric": {"passed": False, "verdict": "weak_match"}},
    )

    assert suggestion["suggested_final_label"] == "memory_failure"
    assert suggestion["suggested_action"] == "promote_to_dataset"
    assert suggestion["suggested_rubric"]["memory_applied"] is False
    assert "golden_replay" in suggestion["suggested_labels"]


async def test_get_review_queue_snapshot_returns_review_and_trace_items():
    items = [
        '{"review_label":"wrong_route","queued_for_review":true,"review_suggestion":{"suggested_final_label":"wrong_route"}}',
        '{"review_label":"tool_failure","queued_for_review":true}',
    ]
    with patch("src.core.conversation_analytics.redis") as mock_redis:
        mock_redis.lrange = AsyncMock(side_effect=[items, items])
        snapshot = await get_review_queue_snapshot(limit=2)

    assert snapshot["review_queue_size"] == 2
    assert snapshot["trace_export_size"] == 2
    assert snapshot["review_queue"][0]["review_label"] == "wrong_route"
    assert (
        snapshot["review_queue"][0]["review_suggestion"]["suggested_final_label"]
        == "wrong_route"
    )


async def test_get_dataset_candidates_returns_recent_items():
    items = [
        '{"trace_key":"corr-1","review":{"final_label":"wrong_route"}}',
    ]
    with patch("src.core.conversation_analytics.redis") as mock_redis:
        mock_redis.lrange = AsyncMock(return_value=items)
        candidates = await get_dataset_candidates(limit=1)

    assert candidates[0]["trace_key"] == "corr-1"
    assert candidates[0]["review"]["final_label"] == "wrong_route"


async def test_get_review_results_returns_recent_items():
    items = [
        '{"trace_key":"corr-1","final_label":"wrong_route","action":"promote_to_dataset"}',
    ]
    with patch("src.core.conversation_analytics.redis") as mock_redis:
        mock_redis.lrange = AsyncMock(return_value=items)
        results = await get_review_results(limit=1)

    assert results[0]["trace_key"] == "corr-1"
    assert results[0]["action"] == "promote_to_dataset"


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


async def test_submit_trace_review_promotes_dataset_candidate():
    trace_payload = {
        "trace_key": "corr-123",
        "review_label": "wrong_route",
        "outcome": "wrong_route",
    }
    serialized_trace = json.dumps(trace_payload)
    with patch("src.core.conversation_analytics.redis") as mock_redis:
        mock_redis.hget = AsyncMock(return_value=serialized_trace)
        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        result = await submit_trace_review(
            trace_key="corr-123",
            reviewer="qa-1",
            final_label="wrong_route",
            action="promote_to_dataset",
            rubric={
                "intent_correct": False,
                "response_useful": False,
                "action_completed": False,
                "clarification_appropriate": True,
                "memory_applied": False,
                "safe": True,
                "language_correct": True,
                "formatting_correct": True,
                "latency_acceptable": True,
            },
            notes="Shadow route diverged from primary.",
            labels=["routing", "shadow"],
        )

    assert result["dataset_candidate_created"] is True
    assert result["review"]["reviewer"] == "qa-1"
    assert result["review"]["final_label"] == "wrong_route"
    assert result["review"]["rubric"]["intent_correct"] is False
    assert result["trace"]["trace_key"] == trace_payload["trace_key"]


async def test_apply_trace_review_suggestion_uses_prefill():
    trace_payload = {
        "trace_key": "corr-123",
        "review_label": "memory_failure",
        "outcome": "wrong_route",
        "review_suggestion": {
            "suggested_final_label": "memory_failure",
            "suggested_action": "promote_to_dataset",
            "suggested_rubric": {
                "intent_correct": True,
                "response_useful": False,
                "action_completed": False,
                "clarification_appropriate": True,
                "memory_applied": False,
                "safe": True,
                "language_correct": True,
                "formatting_correct": True,
                "latency_acceptable": True,
            },
            "suggested_labels": ["memory", "golden_replay"],
            "rationale": "golden replay failure",
        },
    }
    serialized_trace = json.dumps(trace_payload)
    with patch("src.core.conversation_analytics.redis") as mock_redis:
        mock_redis.hget = AsyncMock(return_value=serialized_trace)
        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        result = await apply_trace_review_suggestion(
            trace_key="corr-123",
            reviewer="qa-2",
            notes="confirmed by operator",
            labels=["weekly_review"],
        )

    assert result["review"]["final_label"] == "memory_failure"
    assert result["review"]["action"] == "promote_to_dataset"
    assert "golden replay failure" in result["review"]["notes"]
    assert "confirmed by operator" in result["review"]["notes"]
    assert "weekly_review" in result["review"]["labels"]


async def test_ingest_review_trace_stores_external_candidate():
    with patch("src.core.conversation_analytics.redis") as mock_redis:
        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        payload = await ingest_review_trace(
            {
                "trace_key": "replay-123",
                "channel": "telegram",
                "chat_id": "chat-1",
                "user_id": "user-1",
                "intent": "memory_related",
                "outcome": "wrong_route",
                "tags": ["golden_replay", "memory_related"],
                "message_preview": "Запомни мой бюджет",
                "response_preview": "Я не могу это сделать.",
                "metadata": {"source_trace_key": "corr-1"},
            }
        )

    assert payload["trace_key"] == "replay-123"
    assert payload["review_label"] == "wrong_route"
    assert payload["queued_for_review"] is True
    assert payload["metadata"]["source_trace_key"] == "corr-1"
    assert payload["review_suggestion"]["suggested_action"] == "promote_to_dataset"


async def test_submit_trace_review_rejects_missing_rubric_fields():
    with patch("src.core.conversation_analytics.redis") as mock_redis:
        mock_redis.hget = AsyncMock(return_value='{"trace_key":"corr-123"}')
        try:
            await submit_trace_review(
                trace_key="corr-123",
                reviewer="qa-1",
                final_label="tool_failure",
                action="close",
                rubric={"intent_correct": True},
            )
        except ValueError as exc:
            assert str(exc).startswith("missing_rubric_fields:")
        else:
            raise AssertionError("submit_trace_review should reject partial rubric")


async def test_get_golden_dialogues_formats_candidates():
    candidates = [
        {
            "trace_key": "corr-1",
            "trace": {
                "channel": "telegram",
                "intent": "general_chat",
                "message_preview": "Привет, что ты умеешь?",
                "response_preview": "Могу помочь с задачами.",
                "tags": ["multi_intent"],
            },
            "review": {
                "final_label": "wrong_route",
                "labels": ["routing"],
                "notes": "Нужен более точный route.",
                "rubric": {"intent_correct": False},
                "source_outcome": "wrong_route",
                "source_review_label": "wrong_route",
                "reviewed_at": "2026-03-11T00:00:00+00:00",
            },
            "candidate_created_at": "2026-03-11T00:00:00+00:00",
        }
    ]
    with patch(
        "src.core.conversation_analytics.get_dataset_candidates",
        AsyncMock(return_value=candidates),
    ):
        golden_dialogues = await get_golden_dialogues(limit=1)

    assert golden_dialogues[0]["trace_key"] == "corr-1"
    assert golden_dialogues[0]["scenario"] == "multi_intent"
    assert golden_dialogues[0]["input_text"] == "Привет, что ты умеешь?"
    assert golden_dialogues[0]["assistant_response"] == "Могу помочь с задачами."


async def test_get_weekly_curation_snapshot_aggregates_reviews():
    review_results = [
        {"trace_key": "corr-1", "final_label": "wrong_route", "action": "promote_to_dataset"},
        {"trace_key": "corr-2", "final_label": "tool_failure", "action": "follow_up"},
    ]
    dataset_candidates = [
        {
            "trace_key": "corr-1",
            "trace": {
                "channel": "telegram",
                "intent": "general_chat",
                "message_preview": "Привет",
                "response_preview": "Здравствуйте",
                "tags": [],
            },
            "review": {
                "final_label": "wrong_route",
                "labels": ["routing"],
                "notes": "",
                "rubric": {"intent_correct": False},
                "source_outcome": "wrong_route",
                "source_review_label": "wrong_route",
                "reviewed_at": "2026-03-11T00:00:00+00:00",
            },
            "candidate_created_at": "2026-03-11T00:00:00+00:00",
        }
    ]
    with (
        patch(
            "src.core.conversation_analytics.get_review_results",
            AsyncMock(return_value=review_results),
        ),
        patch(
            "src.core.conversation_analytics.get_dataset_candidates",
            AsyncMock(return_value=dataset_candidates),
        ),
    ):
        snapshot = await get_weekly_curation_snapshot(limit=5)

    assert snapshot["review_result_size"] == 2
    assert snapshot["dataset_candidate_size"] == 1
    assert snapshot["review_label_counts"]["wrong_route"] == 1
    assert snapshot["review_action_counts"]["follow_up"] == 1
    assert snapshot["golden_dialogues"][0]["trace_key"] == "corr-1"
