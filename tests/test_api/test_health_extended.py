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


async def test_analytics_policy_returns_sampling_rules(mock_dependencies):
    policy = {"sample_rates": {"default_success": 10}}
    with patch("api.main.get_conversation_analytics_policy", return_value=policy):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ops/analytics/policy")
    assert resp.status_code == 200
    assert resp.json()["sample_rates"]["default_success"] == 10
