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
        resp = await client.get(
            "/api/browser-connect/test-token",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0"},
        )

    assert resp.status_code == 200
    assert "Sign in to continue" in resp.text
    assert "Connect uber.com" not in resp.text
    assert "Type or paste" in resp.text
    assert "Type into the site" in resp.text
    assert "Browser controls" not in resp.text
    assert "Controls Ready" not in resp.text


async def test_browser_connect_page_debug_mode_exposes_advanced_tools(client):
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
        resp = await client.get("/api/browser-connect/test-token?debug=1")

    assert resp.status_code == 200
    assert "Advanced tools" in resp.text
    assert "Refresh page" in resp.text


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
        resp = await client.get(
            "/api/browser-connect/test-token/state",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["return_url"] == "https://t.me/HurremBot?start=browser_connect_test-token"


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
