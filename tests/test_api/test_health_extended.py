"""Tests for extended health endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app


@pytest.fixture
def mock_dependencies():
    """Mock Redis, DB, circuit breakers, Mem0, and Langfuse."""
    with (
        patch("api.main.redis") as mock_redis,
        patch("api.main.async_session") as mock_session_factory,
    ):
        mock_redis.ping = AsyncMock()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session_factory.return_value = mock_session
        yield mock_redis, mock_session


async def test_health_basic(mock_dependencies):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["api"] == "ok"
    assert data["redis"] == "ok"
    assert data["database"] == "ok"


async def test_health_redis_down(mock_dependencies):
    mock_redis, _ = mock_dependencies
    mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis down"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["redis"] == "error"


async def test_health_detailed_ok(mock_dependencies):
    with (
        patch(
            "src.core.circuit_breaker.all_circuit_statuses",
            return_value={"mem0": {"state": "closed"}, "anthropic": {"state": "closed"}},
        ),
        patch("src.core.memory.mem0_client.get_memory", return_value=MagicMock()),
        patch("src.core.observability.get_langfuse", return_value=MagicMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health/detailed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "circuits" in data
    assert data["mem0"] == "ok"
    assert data["langfuse"] == "ok"


async def test_health_detailed_mem0_error(mock_dependencies):
    with (
        patch(
            "src.core.circuit_breaker.all_circuit_statuses",
            return_value={"mem0": {"state": "open"}},
        ),
        patch(
            "src.core.memory.mem0_client.get_memory",
            side_effect=RuntimeError("Mem0 init failed"),
        ),
        patch("src.core.observability.get_langfuse", return_value=None),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health/detailed")
    data = resp.json()
    # Core services ok → status ok (mem0/langfuse are not core)
    assert data["status"] == "ok"
    assert data["mem0"] == "error"
    assert data["langfuse"] == "not_configured"


async def test_health_detailed_shows_circuits(mock_dependencies):
    circuits_state = {
        "mem0": {"state": "closed", "failure_count": 0},
        "anthropic": {"state": "half_open", "failure_count": 2},
    }
    with (
        patch("src.core.circuit_breaker.all_circuit_statuses", return_value=circuits_state),
        patch("src.core.memory.mem0_client.get_memory", return_value=MagicMock()),
        patch("src.core.observability.get_langfuse", return_value=None),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health/detailed")
    data = resp.json()
    assert data["circuits"]["anthropic"]["state"] == "half_open"


async def test_health_detailed_includes_release_health(mock_dependencies):
    release_health = {
        "status": "degraded",
        "recommended_action": "hold",
        "counts": {"requests_total": 10},
        "rates": {"error_rate": 0.0},
    }
    with (
        patch(
            "src.core.circuit_breaker.all_circuit_statuses",
            return_value={"mem0": {"state": "closed"}},
        ),
        patch("src.core.memory.mem0_client.get_memory", return_value=MagicMock()),
        patch("src.core.observability.get_langfuse", return_value=None),
        patch("api.main.get_release_health_snapshot", AsyncMock(return_value=release_health)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health/detailed")
    data = resp.json()
    assert data["release_health"]["status"] == "degraded"
    assert data["release_health"]["recommended_action"] == "hold"


async def test_release_ops_overview_returns_snapshot(mock_dependencies):
    overview = {
        "switches": {"rollout_name": "canary-a", "shadow_mode": True},
        "flags": {"ff_post_gen_check": True},
        "health": {"status": "healthy", "recommended_action": "continue"},
        "decision": {"next_action": "progress", "target_rollout_percent": 10},
    }
    with patch("api.main.get_release_ops_overview", AsyncMock(return_value=overview)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/release/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["switches"]["shadow_mode"] is True
    assert data["health"]["status"] == "healthy"
    assert data["decision"]["next_action"] == "progress"


async def test_release_ops_overview_requires_auth_when_secret_set(mock_dependencies):
    with patch("api.main.settings.health_secret", "secret-token"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/release/overview")
    assert resp.status_code == 401


async def test_release_ops_decision_returns_guidance(mock_dependencies):
    decision = {
        "current_rollout_percent": 5,
        "target_rollout_percent": 10,
        "next_action": "progress",
        "health_status": "healthy",
    }
    with patch("api.main.get_release_rollout_decision", AsyncMock(return_value=decision)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/release/decision")
    assert resp.status_code == 200
    data = resp.json()
    assert data["next_action"] == "progress"
    assert data["target_rollout_percent"] == 10


async def test_release_ops_overrides_returns_snapshot(mock_dependencies):
    snapshot = {
        "active_override": {"rollout_percent": 10, "shadow_mode": True},
        "action_history": [{"actor": "qa-1", "action": "progress"}],
        "effective_runtime": {"override_active": True},
    }
    with patch("api.main.get_release_override_snapshot", AsyncMock(return_value=snapshot)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/release/overrides?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_override"]["rollout_percent"] == 10
    assert data["action_history"][0]["actor"] == "qa-1"


async def test_release_ops_apply_override_returns_result(mock_dependencies):
    result = {
        "override": {"rollout_percent": 25, "shadow_mode": True},
        "effective_runtime": {"override_active": True},
        "decision": {"next_action": "hold"},
    }
    payload = {
        "actor": "qa-1",
        "action": "progress",
        "rollout_percent": 25,
        "shadow_mode": True,
        "notes": "expand canary",
    }
    with patch("api.main.apply_release_override", AsyncMock(return_value=result)) as mock_apply:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ops/release/overrides", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["override"]["rollout_percent"] == 25
    assert data["decision"]["next_action"] == "hold"
    assert mock_apply.await_args.kwargs["actor"] == "qa-1"


async def test_analytics_policy_returns_sampling_rules(mock_dependencies):
    policy = {"sample_rates": {"default_success": 10}}
    with patch("api.main.get_conversation_analytics_policy", return_value=policy):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/policy")
    assert resp.status_code == 200
    assert resp.json()["sample_rates"]["default_success"] == 10


async def test_analytics_review_queue_returns_snapshot(mock_dependencies):
    snapshot = {
        "review_queue_size": 1,
        "filtered_review_queue_size": 1,
        "trace_export_size": 1,
        "selected_trace_keys": ["trace-1"],
        "review_queue": [],
        "trace_exports": [],
    }
    with patch(
        "api.main.get_review_queue_snapshot",
        AsyncMock(return_value=snapshot),
    ) as mock_snapshot:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/ops/analytics/review-queue?limit=10"
                "&tag=golden_replay&suggested_action=promote_to_dataset&max_selected=25"
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_queue_size"] == 1
    assert data["selected_trace_keys"] == ["trace-1"]
    assert mock_snapshot.await_args.kwargs["tag"] == "golden_replay"
    assert mock_snapshot.await_args.kwargs["suggested_action"] == "promote_to_dataset"


async def test_analytics_submit_review_returns_result(mock_dependencies):
    result = {
        "review": {
            "trace_key": "corr-1",
            "reviewer": "qa-1",
            "final_label": "wrong_route",
            "action": "promote_to_dataset",
        },
        "dataset_candidate_created": True,
        "trace": {"trace_key": "corr-1"},
    }
    payload = {
        "trace_key": "corr-1",
        "reviewer": "qa-1",
        "final_label": "wrong_route",
        "action": "promote_to_dataset",
        "rubric": {
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
        "notes": "Needs routing fix.",
        "labels": ["routing"],
    }
    with patch("api.main.submit_trace_review", AsyncMock(return_value=result)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ops/analytics/reviews", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["dataset_candidate_created"] is True
    assert data["review"]["final_label"] == "wrong_route"


async def test_analytics_apply_review_suggestion_returns_result(mock_dependencies):
    result = {
        "review": {
            "trace_key": "corr-1",
            "reviewer": "qa-1",
            "final_label": "memory_failure",
            "action": "promote_to_dataset",
        },
        "dataset_candidate_created": True,
        "trace": {"trace_key": "corr-1"},
    }
    payload = {
        "trace_key": "corr-1",
        "reviewer": "qa-1",
        "notes": "confirmed",
        "labels": ["weekly_review"],
    }
    with patch("api.main.apply_trace_review_suggestion", AsyncMock(return_value=result)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ops/analytics/reviews/apply-suggestion", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["dataset_candidate_created"] is True
    assert data["review"]["action"] == "promote_to_dataset"


async def test_analytics_apply_review_suggestions_batch_returns_summary(mock_dependencies):
    result = {
        "requested": 2,
        "applied_count": 1,
        "failed_count": 1,
        "applied": [{"trace_key": "corr-1"}],
        "failed": [{"trace_key": "corr-2", "error": "trace_not_found"}],
        "selection": {"selected_trace_keys": ["corr-1", "corr-2"]},
    }
    payload = {
        "trace_keys": [],
        "reviewer": "qa-1",
        "notes": "weekly review",
        "labels": ["weekly_review"],
        "tag": "golden_replay",
        "suggested_action": "promote_to_dataset",
        "source": "test_bot_live_golden_replay",
    }
    with patch(
        "api.main.apply_trace_review_suggestions_batch",
        AsyncMock(return_value=result),
    ) as mock_batch:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/ops/analytics/reviews/apply-suggestions-batch",
                json=payload,
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data["requested"] == 2
    assert data["applied_count"] == 1
    assert data["failed_count"] == 1
    assert data["selection"]["selected_trace_keys"] == ["corr-1", "corr-2"]
    assert mock_batch.await_args.kwargs["tag"] == "golden_replay"
    assert mock_batch.await_args.kwargs["suggested_action"] == "promote_to_dataset"


async def test_analytics_ingest_review_candidate_returns_trace(mock_dependencies):
    trace = {
        "trace_key": "replay-1",
        "review_label": "wrong_route",
        "queued_for_review": True,
    }
    payload = {
        "trace_key": "replay-1",
        "channel": "telegram",
        "chat_id": "chat-1",
        "user_id": "user-1",
        "intent": "memory_related",
        "outcome": "wrong_route",
        "review_label": "wrong_route",
        "tags": ["golden_replay", "memory_related"],
        "message_preview": "Запомни мой бюджет",
        "response_preview": "Не могу помочь.",
        "metadata": {"source_trace_key": "corr-1"},
    }
    with patch("api.main.ingest_review_trace", AsyncMock(return_value=trace)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ops/analytics/review-candidates", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["trace"]["trace_key"] == "replay-1"
    assert data["trace"]["queued_for_review"] is True


async def test_analytics_dataset_candidates_returns_snapshot(mock_dependencies):
    candidates = [
        {
            "trace_key": "corr-1",
            "review": {"final_label": "wrong_route"},
        }
    ]
    with (
        patch("api.main.get_dataset_candidates", AsyncMock(return_value=candidates)),
        patch(
            "api.main.get_conversation_analytics_policy",
            return_value={"review_actions": ["promote_to_dataset"]},
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/dataset-candidates?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dataset_candidate_size"] == 1
    assert data["dataset_candidates"][0]["trace_key"] == "corr-1"


async def test_analytics_review_results_returns_snapshot(mock_dependencies):
    results = [
        {"trace_key": "corr-1", "final_label": "wrong_route", "action": "promote_to_dataset"},
    ]
    with (
        patch("api.main.get_review_results", AsyncMock(return_value=results)),
        patch(
            "api.main.get_conversation_analytics_policy",
            return_value={"review_actions": ["promote_to_dataset"]},
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/review-results?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_result_size"] == 1
    assert data["review_results"][0]["trace_key"] == "corr-1"


async def test_analytics_review_batches_returns_snapshot(mock_dependencies):
    batches = [
        {
            "batch_id": "review-batch:1",
            "reviewer": "qa-1",
            "applied_count": 2,
            "failed_count": 0,
        }
    ]
    with (
        patch("api.main.get_review_batches", AsyncMock(return_value=batches)),
        patch(
            "api.main.get_conversation_analytics_policy",
            return_value={"review_batch_limit": 200},
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/review-batches?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_batch_size"] == 1
    assert data["review_batches"][0]["batch_id"] == "review-batch:1"


async def test_analytics_feedback_returns_snapshot(mock_dependencies):
    feedback = [
        {
            "token": "token-1",
            "trace_key": "corr-1",
            "feedback": "helpful",
        }
    ]
    with (
        patch("api.main.get_user_feedback", AsyncMock(return_value=feedback)),
        patch(
            "api.main.get_conversation_analytics_policy",
            return_value={"feedback_values": ["helpful", "unhelpful"]},
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/feedback?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["feedback_size"] == 1
    assert data["feedback"][0]["trace_key"] == "corr-1"


async def test_analytics_quality_metrics_returns_snapshot(mock_dependencies):
    snapshot = {
        "status": "monitor",
        "review_count": 5,
        "review_queue_size": 2,
        "dataset_candidate_size": 3,
        "feedback_count": 4,
        "rates": {
            "wrong_route_rate": 0.2,
            "task_completion_rate": 0.8,
            "user_dissatisfaction_signal_rate": 0.25,
        },
    }
    with patch("api.main.get_quality_metrics_snapshot", AsyncMock(return_value=snapshot)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/quality-metrics?limit=50")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "monitor"
    assert data["review_count"] == 5
    assert data["rates"]["wrong_route_rate"] == 0.2


async def test_analytics_golden_dialogues_returns_snapshot(mock_dependencies):
    golden_dialogues = [
        {"trace_key": "corr-1", "scenario": "general", "input_text": "Привет"},
    ]
    with (
        patch("api.main.get_golden_dialogues", AsyncMock(return_value=golden_dialogues)),
        patch(
            "api.main.get_conversation_analytics_policy",
            return_value={"review_actions": ["promote_to_dataset"]},
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/golden-dialogues?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["golden_dialogue_size"] == 1
    assert data["golden_dialogues"][0]["trace_key"] == "corr-1"


async def test_analytics_weekly_curation_returns_snapshot(mock_dependencies):
    snapshot = {
        "review_result_size": 2,
        "dataset_candidate_size": 1,
        "review_batch_size": 1,
        "feedback_size": 1,
        "review_label_counts": {"wrong_route": 1},
        "review_action_counts": {"promote_to_dataset": 1},
        "feedback_counts": {"unhelpful": 1},
        "recent_reviews": [],
        "recent_review_batches": [{"batch_id": "review-batch:1"}],
        "recent_feedback": [{"token": "token-1"}],
        "golden_dialogues": [],
    }
    with patch("api.main.get_weekly_curation_snapshot", AsyncMock(return_value=snapshot)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/weekly-curation?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_result_size"] == 2
    assert data["review_batch_size"] == 1
    assert data["feedback_size"] == 1
    assert data["review_action_counts"]["promote_to_dataset"] == 1
