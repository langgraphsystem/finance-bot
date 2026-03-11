"""Tests for voice webhook and route wiring."""

from dataclasses import asdict
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.voice.review_store import VoiceCallReview
from src.voice.routes import router
from src.voice.session_store import VoiceCallMetadata
from src.voice.trace import VoiceTraceEvent


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


async def test_inbound_voice_webhook_returns_twiml():
    app = _build_app()
    transport = ASGITransport(app=app)

    with (
        patch("src.voice.routes.voice_session_store.save", new_callable=AsyncMock) as mock_save,
        patch("src.voice.routes.voice_config.ws_base_url", "wss://example.com"),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/webhook/voice/inbound",
                data={"CallSid": "CA123", "From": "+15551234567"},
            )

    assert response.status_code == 200
    assert "<Stream" in response.text
    assert "wss://example.com/ws/voice/inbound/CA123" in response.text
    mock_save.assert_awaited_once()


async def test_outbound_voice_webhook_uses_stored_session():
    app = _build_app()
    transport = ASGITransport(app=app)
    metadata = VoiceCallMetadata(
        call_id="call-123",
        call_type="outbound",
        owner_name="David",
        business_name="North Star Plumbing",
        services="plumbing",
        hours="Mon-Fri 9-5",
    )

    with (
        patch(
            "src.voice.routes.voice_session_store.get",
            new_callable=AsyncMock,
            return_value=metadata,
        ),
        patch("src.voice.routes.voice_config.ws_base_url", "wss://example.com"),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/webhook/voice/outbound/call-123")

    assert response.status_code == 200
    assert "wss://example.com/ws/voice/outbound/call-123" in response.text


async def test_status_webhook_updates_stored_session_status():
    app = _build_app()
    transport = ASGITransport(app=app)

    with patch(
        "src.voice.routes.voice_session_store.update_status",
        new_callable=AsyncMock,
    ) as mock_update:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/webhook/voice/status?call_id=call-123",
                data={"CallStatus": "completed"},
            )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_update.assert_awaited_once_with("call-123", "completed")


async def test_main_app_includes_voice_router():
    from api.main import app

    paths = {route.path for route in app.routes}
    assert "/webhook/voice/inbound" in paths
    assert "/webhook/voice/outbound/{call_id}" in paths
    assert "/ws/voice/{call_type}/{call_id}" in paths


async def test_voice_review_endpoint_returns_review_and_trace():
    app = _build_app()
    transport = ASGITransport(app=app)
    review = VoiceCallReview(
        call_id="call-123",
        created_at="2026-03-10T00:00:00Z",
        call_type="inbound",
        caller="John",
        duration_seconds=42,
        disposition="completed_with_tools",
        summary_text="Summary",
        tool_names=["create_booking"],
        qa_score=92,
        qa_status="pass",
    )
    metadata = VoiceCallMetadata(
        call_id="call-123",
        call_type="inbound",
        owner_name="David",
        business_name="North Star Plumbing",
        services="plumbing",
        hours="Mon-Fri 9-5",
    )
    trace = [
        VoiceTraceEvent(
            timestamp="2026-03-10T00:00:00Z",
            kind="call_started",
            payload={"call_type": "inbound"},
        )
    ]

    with (
        patch(
            "src.voice.routes.voice_review_store.load",
            new_callable=AsyncMock,
            return_value=review,
        ),
        patch(
            "src.voice.routes.voice_session_store.get",
            new_callable=AsyncMock,
            return_value=metadata,
        ),
        patch(
            "src.voice.routes.voice_trace_store.load",
            new_callable=AsyncMock,
            return_value=trace,
        ),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/voice/review/call-123")

    assert response.status_code == 200
    assert response.json()["review"] == asdict(review)
    assert response.json()["metadata"] == asdict(metadata)
    assert response.json()["trace"] == [asdict(item) for item in trace]


async def test_recent_voice_reviews_endpoint_returns_items():
    app = _build_app()
    transport = ASGITransport(app=app)
    review = VoiceCallReview(
        call_id="call-123",
        created_at="2026-03-10T00:00:00Z",
        call_type="inbound",
        caller="John",
        duration_seconds=42,
        disposition="completed_with_tools",
        summary_text="Summary",
        qa_score=92,
        qa_status="pass",
    )

    with patch(
        "src.voice.routes.voice_review_store.recent",
        new_callable=AsyncMock,
        return_value=[review],
    ) as mock_recent:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/voice/review/recent?limit=5")

    assert response.status_code == 200
    assert response.json() == {"items": [asdict(review)]}
    mock_recent.assert_awaited_once_with(limit=5)


async def test_voice_ops_overview_endpoint_returns_aggregates():
    app = _build_app()
    transport = ASGITransport(app=app)
    review = VoiceCallReview(
        call_id="call-123",
        created_at="2026-03-10T00:00:00Z",
        call_type="inbound",
        caller="John",
        duration_seconds=42,
        disposition="completed_with_tools",
        summary_text="Summary",
        tool_names=["schedule_callback"],
        qa_score=92,
        qa_status="pass",
    )

    with patch(
        "src.voice.routes.voice_review_store.recent",
        new_callable=AsyncMock,
        return_value=[review],
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/voice/ops/overview?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_calls"] == 1
    assert payload["callbacks_requested"] == 1


async def test_voice_ops_switches_endpoint_returns_config_state():
    app = _build_app()
    transport = ASGITransport(app=app)

    with patch(
        "src.voice.routes.voice_config.rollout_state",
        return_value={
            "enabled": True,
            "allow_outbound": False,
            "allow_write_tools": True,
            "receptionist_only": False,
            "force_callback_mode": True,
        },
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/voice/ops/switches")

    assert response.status_code == 200
    assert response.json()["force_callback_mode"] is True


async def test_voice_ops_readiness_endpoint_returns_report():
    app = _build_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/voice/ops/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert "ready" in payload
    assert "checks" in payload


async def test_inbound_voice_webhook_returns_unavailable_when_voice_disabled():
    app = _build_app()
    transport = ASGITransport(app=app)

    with patch("src.voice.routes.voice_config.enabled", False):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/webhook/voice/inbound", data={"CallSid": "CA123"})

    assert response.status_code == 200
    assert "<Say>" in response.text


async def test_voice_simulation_route_runs_builtin_scenario():
    app = _build_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/voice/simulations/inbound_booking_success")

    assert response.status_code == 200
    payload = response.json()
    assert payload["passed"] is True
    assert payload["summary"]["disposition"] == "completed_with_tools"
