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


def test_build_client_profile_uses_mobile_viewport_for_phone():
    profile = remote_browser_connect._build_client_profile(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15"
    )

    assert profile.is_mobile is True
    assert profile.has_touch is True
    assert profile.viewport == {
        "width": remote_browser_connect.MOBILE_VIEWPORT_WIDTH,
        "height": remote_browser_connect.MOBILE_VIEWPORT_HEIGHT,
    }


def test_build_client_profile_uses_desktop_viewport_for_computer():
    profile = remote_browser_connect._build_client_profile(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0"
    )

    assert profile.is_mobile is False
    assert profile.has_touch is False
    assert profile.viewport == {
        "width": remote_browser_connect.DESKTOP_VIEWPORT_WIDTH,
        "height": remote_browser_connect.DESKTOP_VIEWPORT_HEIGHT,
    }
