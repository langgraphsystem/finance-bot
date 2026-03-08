"""Tests for hosted browser connect API."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.browser_connect import router

app = FastAPI()
app.include_router(router)


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_browser_connect_page_renders_provider(client):
    with patch(
        "api.browser_connect.remote_browser_connect.get_session_state",
        new_callable=AsyncMock,
        return_value={
            "status": "active",
            "provider": "uber.com",
            "current_url": "https://m.uber.com/go/home",
            "error": "",
        },
    ):
        resp = await client.get("/api/browser-connect/test-token")

    assert resp.status_code == 200
    assert "Connect uber.com" in resp.text
    assert "remote browser" in resp.text.lower()


async def test_browser_connect_state_returns_telegram_deep_link(client):
    with (
        patch(
            "api.browser_connect.remote_browser_connect.get_session_state",
            new_callable=AsyncMock,
            return_value={
                "status": "completed",
                "provider": "uber.com",
                "current_url": "https://m.uber.com/go/home",
                "error": "",
            },
        ),
        patch(
            "api.browser_connect.get_bot_username",
            new_callable=AsyncMock,
            return_value="HurremBot",
        ),
    ):
        resp = await client.get("/api/browser-connect/test-token/state")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["return_url"] == "https://t.me/HurremBot?start=browser_connect"


async def test_browser_connect_action_proxies_to_manager(client):
    with (
        patch(
            "api.browser_connect.remote_browser_connect.apply_action",
            new_callable=AsyncMock,
            return_value={
                "status": "active",
                "provider": "uber.com",
                "current_url": "https://m.uber.com/login",
                "error": "",
            },
        ) as mock_action,
        patch(
            "api.browser_connect.get_bot_username",
            new_callable=AsyncMock,
            return_value="HurremBot",
        ),
    ):
        resp = await client.post(
            "/api/browser-connect/test-token/action",
            json={"action": "click", "x": 100, "y": 220},
        )

    assert resp.status_code == 200
    mock_action.assert_awaited_once()
    assert resp.json()["provider"] == "uber.com"
