"""Tests for hosted browser connect helpers."""

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
