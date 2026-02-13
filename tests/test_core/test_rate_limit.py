"""Tests for rate limiter."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_rate_limit_allows_under_limit():
    """First request should be allowed (count=1, under default limit of 30)."""
    with (
        patch("src.core.rate_limit.redis") as mock_redis,
        patch("src.core.rate_limit.settings") as mock_settings,
    ):
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_settings.rate_limit_per_minute = 30

        from src.core.rate_limit import check_rate_limit

        result = await check_rate_limit("user1")
        assert result is True
        mock_redis.expire.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_blocks_over_limit():
    """Request over the per-minute limit should be blocked."""
    with (
        patch("src.core.rate_limit.redis") as mock_redis,
        patch("src.core.rate_limit.settings") as mock_settings,
    ):
        mock_redis.incr = AsyncMock(return_value=31)
        mock_settings.rate_limit_per_minute = 30

        from src.core.rate_limit import check_rate_limit

        result = await check_rate_limit("user1")
        assert result is False


@pytest.mark.asyncio
async def test_rate_limit_allows_at_exact_limit():
    """Request exactly at the limit should still be allowed (<=)."""
    with (
        patch("src.core.rate_limit.redis") as mock_redis,
        patch("src.core.rate_limit.settings") as mock_settings,
    ):
        mock_redis.incr = AsyncMock(return_value=30)
        mock_settings.rate_limit_per_minute = 30

        from src.core.rate_limit import check_rate_limit

        result = await check_rate_limit("user1")
        assert result is True


@pytest.mark.asyncio
async def test_rate_limit_fails_open():
    """Redis failure should allow request (fail open)."""
    with patch("src.core.rate_limit.redis") as mock_redis:
        mock_redis.incr = AsyncMock(side_effect=Exception("Redis down"))

        from src.core.rate_limit import check_rate_limit

        result = await check_rate_limit("user1")
        assert result is True


@pytest.mark.asyncio
async def test_rate_limit_expire_only_on_first():
    """Expire should only be called when count == 1 (new key)."""
    with (
        patch("src.core.rate_limit.redis") as mock_redis,
        patch("src.core.rate_limit.settings") as mock_settings,
    ):
        mock_redis.incr = AsyncMock(return_value=5)
        mock_redis.expire = AsyncMock()
        mock_settings.rate_limit_per_minute = 30

        from src.core.rate_limit import check_rate_limit

        await check_rate_limit("user1")
        mock_redis.expire.assert_not_awaited()
