"""Tests for PlanCache — Redis-backed agentic plan caching."""

from unittest.mock import AsyncMock, patch

from src.core.plan_cache import BRIEF_TTL, DEFAULT_TTL, TOOL_PLAN_TTL, PlanCache


class TestComputeHash:
    def test_deterministic(self):
        h1 = PlanCache.compute_hash(user_id="u1", intent="morning_brief")
        h2 = PlanCache.compute_hash(user_id="u1", intent="morning_brief")
        assert h1 == h2

    def test_different_params_different_hash(self):
        h1 = PlanCache.compute_hash(user_id="u1", intent="morning_brief")
        h2 = PlanCache.compute_hash(user_id="u2", intent="morning_brief")
        assert h1 != h2

    def test_hash_length(self):
        h = PlanCache.compute_hash(a="hello", b=42)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_key_order_irrelevant(self):
        h1 = PlanCache.compute_hash(a="x", b="y")
        h2 = PlanCache.compute_hash(b="y", a="x")
        assert h1 == h2


class TestPlanCacheGet:
    async def test_returns_cached_data(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"response_text": "Good morning!"}')

        with patch("src.core.db.redis", mock_redis):
            result = await PlanCache.get("brief", user_id="u1", intent="morning_brief")

        assert result == {"response_text": "Good morning!"}
        mock_redis.get.assert_called_once()

    async def test_returns_none_on_miss(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("src.core.db.redis", mock_redis):
            result = await PlanCache.get("brief", user_id="u1", intent="morning_brief")

        assert result is None

    async def test_returns_none_on_error(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("src.core.db.redis", mock_redis):
            result = await PlanCache.get("brief", user_id="u1")

        assert result is None


class TestPlanCachePut:
    async def test_stores_data_with_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("src.core.db.redis", mock_redis):
            await PlanCache.put(
                "brief",
                {"response_text": "Hello"},
                ttl=BRIEF_TTL,
                user_id="u1",
                intent="morning_brief",
            )

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args.kwargs.get("ex") == BRIEF_TTL

    async def test_default_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("src.core.db.redis", mock_redis):
            await PlanCache.put("tools", {"tool_hint": "query_data"}, user_id="u1")

        call_args = mock_redis.set.call_args
        assert call_args.kwargs.get("ex") == DEFAULT_TTL

    async def test_handles_error_gracefully(self):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("src.core.db.redis", mock_redis):
            # Should not raise
            await PlanCache.put("brief", {"text": "hi"}, user_id="u1")


class TestPlanCacheInvalidate:
    async def test_deletes_key(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("src.core.db.redis", mock_redis):
            await PlanCache.invalidate("brief", user_id="u1", intent="morning_brief")

        mock_redis.delete.assert_called_once()

    async def test_handles_error_gracefully(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("src.core.db.redis", mock_redis):
            await PlanCache.invalidate("brief", user_id="u1")


class TestKeyFormat:
    async def test_key_contains_scope_and_hash(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("src.core.db.redis", mock_redis):
            await PlanCache.get("brief", user_id="u1")

        key = mock_redis.get.call_args[0][0]
        assert key.startswith("plan:brief:")
        assert len(key) == len("plan:brief:") + 16


class TestConstants:
    def test_ttl_values(self):
        assert DEFAULT_TTL == 86400
        assert BRIEF_TTL == 300
        assert TOOL_PLAN_TTL == 43200
