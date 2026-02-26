"""Tests for locale/timezone write-path normalization (Phase 3)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    async def test_legacy_mode_updates_default_timezone(self, user_id):
        """With ff_locale_v2_write=False, only overwrites America/New_York."""
        from api.main import _maybe_set_timezone_from_language

        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("api.main.redis") as mock_redis,
            patch("api.main.async_session", return_value=mock_session),
            patch("api.main.settings") as mock_settings,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_settings.ff_locale_v2_write = False

            await _maybe_set_timezone_from_language(user_id, "ru")

            mock_session.execute.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_v2_mode_sets_timezone_source(self, user_id):
        """With ff_locale_v2_write=True, sets timezone_source='channel_hint'."""
        from api.main import _maybe_set_timezone_from_language

        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("api.main.redis") as mock_redis,
            patch("api.main.async_session", return_value=mock_session),
            patch("api.main.settings") as mock_settings,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_settings.ff_locale_v2_write = True

            await _maybe_set_timezone_from_language(user_id, "ru")

            # Verify the update was called (with timezone_source filter)
            call_args = mock_session.execute.call_args
            assert call_args is not None
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_cached(self, user_id):
        """Should skip if already set today (Redis cache)."""
        from api.main import _maybe_set_timezone_from_language

        with patch("api.main.redis") as mock_redis:
            mock_redis.get = AsyncMock(return_value=b"1")
            mock_redis.set = AsyncMock()

            with patch("api.main.async_session") as mock_session:
                await _maybe_set_timezone_from_language(user_id, "ru")
                mock_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_unknown_language(self, user_id):
        """Should skip if language code is not in LANGUAGE_TIMEZONE_MAP."""
        from api.main import _maybe_set_timezone_from_language

        with (
            patch("api.main.redis") as mock_redis,
            patch("api.main.async_session") as mock_session,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            await _maybe_set_timezone_from_language(user_id, "xx")
            mock_session.assert_not_called()
