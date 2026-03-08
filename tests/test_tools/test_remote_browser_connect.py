"""Tests for hosted browser connect helpers."""

import time
from unittest.mock import AsyncMock, patch

from src.tools import remote_browser_connect


async def test_create_connect_url_stores_token_payload():
    mock_redis = AsyncMock()

    with (
        patch("src.tools.remote_browser_connect.redis", mock_redis),
        patch.object(
            remote_browser_connect.settings,
            "google_redirect_uri",
            "https://bot.example.com/oauth/google/callback",
        ),
    ):
        url = await remote_browser_connect.create_connect_url(
            "user-1",
            "family-1",
            "m.uber.com",
        )

    assert url.startswith("https://bot.example.com/api/browser-connect/")
    mock_redis.set.assert_awaited_once()
    args = mock_redis.set.await_args.args
    assert args[0].startswith("browser_connect:")
    assert '"provider": "uber.com"' in args[1]


async def test_looks_authenticated_rejects_uber_guest_page():
    session = remote_browser_connect.RemoteBrowserSession(
        token="tok",
        user_id="user-1",
        family_id="family-1",
        provider="uber.com",
        playwright=None,
        browser=None,
        context=AsyncMock(),
        page=AsyncMock(),
        created_at=time.time(),
        updated_at=time.time(),
    )
    session.page.text_content = AsyncMock(
        return_value="Uber Login Continue with Google Continue with Apple"
    )

    result = await remote_browser_connect._looks_authenticated(session)

    assert result is False


async def test_looks_authenticated_accepts_uber_account_page():
    session = remote_browser_connect.RemoteBrowserSession(
        token="tok",
        user_id="user-1",
        family_id="family-1",
        provider="uber.com",
        playwright=None,
        browser=None,
        context=AsyncMock(),
        page=AsyncMock(),
        created_at=time.time(),
        updated_at=time.time(),
    )
    session.page.text_content = AsyncMock(return_value="Where to? Activity Wallet Account")

    result = await remote_browser_connect._looks_authenticated(session)

    assert result is True
