"""Tests for locale/timezone write-path normalization (Phase 3)."""

import uuid
from unittest.mock import AsyncMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# _maybe_set_timezone_from_language
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id():
    return str(uuid.uuid4())


class TestMaybeSetTimezoneFromLanguage:
    """Tests for api.main._maybe_set_timezone_from_language."""

    @pytest.mark.asyncio
    async def test_skips_english(self, user_id):
        """English is ambiguous — should not attempt any timezone guess."""
        from api.main import _maybe_set_timezone_from_language

        with patch("api.main.redis") as mock_redis:
            await _maybe_set_timezone_from_language(user_id, "en")
            mock_redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_empty_language(self, user_id):
        from api.main import _maybe_set_timezone_from_language

        with patch("api.main.redis") as mock_redis:
            await _maybe_set_timezone_from_language(user_id, "")
            mock_redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_russian_delegates_to_maybe_update(self, user_id):
        """Russian language_code should call maybe_update_timezone with Europe/Moscow."""
        from api.main import _maybe_set_timezone_from_language

        with (
            patch("api.main.redis") as mock_redis,
            patch(
                "src.core.timezone.maybe_update_timezone",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_update,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            await _maybe_set_timezone_from_language(user_id, "ru")

            mock_update.assert_awaited_once_with(
                user_id, "Europe/Moscow", "channel_hint", 30
            )

    @pytest.mark.asyncio
    async def test_kyrgyz_maps_to_bishkek(self, user_id):
        from api.main import _maybe_set_timezone_from_language

        with (
            patch("api.main.redis") as mock_redis,
            patch(
                "src.core.timezone.maybe_update_timezone",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_update,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            await _maybe_set_timezone_from_language(user_id, "ky")

            mock_update.assert_awaited_once_with(
                user_id, "Asia/Bishkek", "channel_hint", 30
            )

    @pytest.mark.asyncio
    async def test_skips_when_cached(self, user_id):
        """Should skip if already set today (Redis cache)."""
        from api.main import _maybe_set_timezone_from_language

        with patch("api.main.redis") as mock_redis:
            mock_redis.get = AsyncMock(return_value=b"1")
            mock_redis.set = AsyncMock()

            with patch(
                "src.core.timezone.maybe_update_timezone",
                new_callable=AsyncMock,
            ) as mock_update:
                await _maybe_set_timezone_from_language(user_id, "ru")
                mock_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_unknown_language(self, user_id):
        """Should skip if language code is not in LANGUAGE_TIMEZONE_MAP."""
        from api.main import _maybe_set_timezone_from_language

        with (
            patch("api.main.redis") as mock_redis,
            patch(
                "src.core.timezone.maybe_update_timezone",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            await _maybe_set_timezone_from_language(user_id, "xx")
            mock_update.assert_not_awaited()


class TestMaybeSetTimezoneFromSlack:
    """Tests for api.main._maybe_set_timezone_from_slack."""

    @pytest.mark.asyncio
    async def test_caches_only_after_success(self, user_id):
        from api.main import _maybe_set_timezone_from_slack

        slack_gw = AsyncMock()
        slack_gw.get_user_timezone = AsyncMock(
            return_value=("Europe/Berlin", "de-DE", True)
        )

        with (
            patch("api.main.redis") as mock_redis,
            patch("api.main._slack_gw", slack_gw),
            patch(
                "src.core.timezone.maybe_update_timezone",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_update,
        ):
            mock_redis.get = AsyncMock(side_effect=[None, None])
            mock_redis.set = AsyncMock()

            await _maybe_set_timezone_from_slack(user_id, "U123")

            mock_update.assert_awaited_once_with(
                user_id, "Europe/Berlin", "slack_api", 85
            )
            assert mock_redis.set.await_args_list == [
                call(f"tz_slack:{user_id}", "1", ex=86400 * 7)
            ]

    @pytest.mark.asyncio
    async def test_sets_short_retry_backoff_for_retryable_failure(self, user_id):
        from api.main import _maybe_set_timezone_from_slack
        from src.gateway.slack_gw import SlackRetryableError

        slack_gw = AsyncMock()
        slack_gw.get_user_timezone = AsyncMock(side_effect=SlackRetryableError("429"))

        with (
            patch("api.main.redis") as mock_redis,
            patch("api.main._slack_gw", slack_gw),
            patch(
                "src.core.timezone.maybe_update_timezone",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            mock_redis.get = AsyncMock(side_effect=[None, None])
            mock_redis.set = AsyncMock()

            await _maybe_set_timezone_from_slack(user_id, "U123")

            mock_update.assert_not_awaited()
            assert mock_redis.set.await_args_list == [
                call(f"tz_slack_retry:{user_id}", "1", ex=300)
            ]
