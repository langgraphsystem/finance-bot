"""Tests for voice webhook and route wiring."""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.voice.routes import router
from src.voice.session_store import VoiceCallMetadata


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
