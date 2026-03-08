"""Tests for browser extension API endpoints."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.browser_extension import router

_TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
_TEST_FAMILY_ID = "00000000-0000-0000-0000-000000000002"
_TEST_TOKEN = "test-token-abc123"

app = FastAPI()
app.include_router(router)


@pytest.fixture
def mock_redis():
    with patch("api.browser_extension.redis") as m:
        m.get = AsyncMock(return_value=_TEST_USER_ID)
        yield m


@pytest.fixture
def mock_db_session():
    """Mock async_session to return user with family_id."""
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, idx: uuid.UUID(_TEST_FAMILY_ID)

    mock_result = MagicMock()
    mock_result.one_or_none.return_value = mock_row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("api.browser_extension.async_session", return_value=mock_session):
        yield mock_session


@pytest.fixture
def client(mock_redis, mock_db_session):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_save_session(client):
    with patch(
        "api.browser_extension.browser_service.save_storage_state",
        new_callable=AsyncMock,
    ) as mock_save:
        resp = await client.post(
            "/api/ext/session",
            json={
                "site": "booking.com",
                "cookies": [
                    {
                        "name": "session_id",
                        "value": "abc123",
                        "domain": ".booking.com",
                        "path": "/",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["site"] == "booking.com"
    mock_save.assert_called_once()
    args = mock_save.call_args
    assert args[0][0] == _TEST_USER_ID  # user_id
    assert args[0][1] == _TEST_FAMILY_ID  # family_id
    assert args[0][2] == "booking.com"  # domain


async def test_save_session_no_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/ext/session",
            json={"site": "booking.com", "cookies": []},
        )
    assert resp.status_code == 422  # Missing required header


async def test_save_session_invalid_token():
    with (
        patch("api.browser_extension.redis") as mock_redis,
        patch("api.browser_extension.async_session"),
    ):
        mock_redis.get = AsyncMock(return_value=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/ext/session",
                json={"site": "booking.com", "cookies": []},
                headers={"Authorization": "Bearer invalid-token"},
            )
    assert resp.status_code == 401


async def test_list_sessions(client):
    """Test listing sessions returns site info."""
    mock_encrypted = b"encrypted_data"
    mock_row = MagicMock()
    mock_row.site = "booking.com"
    mock_row.updated_at = MagicMock()
    mock_row.updated_at.isoformat.return_value = "2026-02-22T10:00:00"
    mock_row.storage_state_encrypted = mock_encrypted

    # Override the second DB call (list query) — first call is user lookup
    mock_session = AsyncMock()
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # User lookup
            mock_user_row = MagicMock()
            mock_user_row.__getitem__ = lambda self, idx: uuid.UUID(_TEST_FAMILY_ID)
            result = MagicMock()
            result.one_or_none.return_value = mock_user_row
            return result
        else:
            # Session list
            result = MagicMock()
            result.all.return_value = [mock_row]
            return result

    mock_session.execute = AsyncMock(side_effect=side_effect)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("api.browser_extension.redis") as mock_redis,
        patch("api.browser_extension.async_session", return_value=mock_session),
        patch(
            "api.browser_extension.decrypt_token",
            return_value=json.dumps({"cookies": [{"name": "a"}, {"name": "b"}]}),
        ),
    ):
        mock_redis.get = AsyncMock(return_value=_TEST_USER_ID)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                "/api/ext/sessions",
                headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["site"] == "booking.com"
    assert data["sessions"][0]["cookie_count"] == 2


async def test_extension_status(client):
    with (
        patch(
            "api.browser_extension.browser_service.list_user_sessions",
            new_callable=AsyncMock,
            return_value=[
                {"site": "booking.com", "updated_at": "2026-03-07", "expired": False},
                {"site": "amazon.com", "updated_at": "2026-03-07", "expired": False},
            ],
        ),
        patch(
            "api.browser_extension.get_bot_username",
            new_callable=AsyncMock,
            return_value="HurremBot",
        ),
    ):
        resp = await client.get(
            "/api/ext/status",
            headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["user_id"] == _TEST_USER_ID
    assert data["family_id"] == _TEST_FAMILY_ID
    assert data["session_count"] == 2
    assert data["sites"] == ["amazon.com", "booking.com"]
    assert data["bot_username"] == "HurremBot"


async def test_extension_connect_redirects_to_provider_login(client):
    resp = await client.get("/api/ext/connect", params={"provider": "uber.com"})

    assert resp.status_code == 200
    assert "Connecting Uber" in resp.text
    assert "https://m.uber.com/go/home" in resp.text


async def test_delete_session(client):
    with patch(
        "api.browser_extension.browser_service.delete_session",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = await client.delete(
            "/api/ext/session/booking.com",
            headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_delete_session_not_found(client):
    with patch(
        "api.browser_extension.browser_service.delete_session",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = await client.delete(
            "/api/ext/session/unknown.com",
            headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        )

    assert resp.status_code == 404


async def test_save_session_multiple_cookies(client):
    """Test saving multiple cookies for a site."""
    cookies = [
        {"name": "sid", "value": "abc", "domain": ".booking.com"},
        {"name": "lang", "value": "en", "domain": ".booking.com"},
        {"name": "pref", "value": "1", "domain": "booking.com", "httpOnly": True, "secure": True},
    ]
    with patch(
        "api.browser_extension.browser_service.save_storage_state",
        new_callable=AsyncMock,
    ) as mock_save:
        resp = await client.post(
            "/api/ext/session",
            json={"site": "www.booking.com", "cookies": cookies},
            headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        )

    assert resp.status_code == 200
    assert resp.json()["site"] == "booking.com"  # Domain normalized
    call_args = mock_save.call_args[0]
    storage_state = call_args[3]
    assert len(storage_state["cookies"]) == 3
    assert storage_state["origins"] == []
