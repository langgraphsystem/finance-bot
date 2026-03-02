"""Tests for in-session buffer (Phase 2.2)."""

import json
from unittest.mock import AsyncMock, patch

from src.core.memory.session_buffer import (
    MAX_BUFFER_ITEMS,
    REDIS_KEY_PREFIX,
    SESSION_BUFFER_TTL,
    clear_session_buffer,
    format_buffer_block,
    get_session_buffer,
    update_session_buffer,
)


class TestGetSessionBuffer:
    async def test_returns_parsed_facts(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [
            json.dumps({"fact": "salary 6000", "category": "income"}),
            json.dumps({"fact": "budget groceries 500", "category": "budget_limit"}),
        ]
        with patch("src.core.memory.session_buffer.redis", mock_redis):
            result = await get_session_buffer("user-1")
        assert len(result) == 2
        assert result[0]["fact"] == "salary 6000"
        mock_redis.lrange.assert_called_once_with(f"{REDIS_KEY_PREFIX}:user-1", 0, -1)

    async def test_returns_empty_on_redis_failure(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.side_effect = Exception("Redis down")
        with patch("src.core.memory.session_buffer.redis", mock_redis):
            result = await get_session_buffer("user-1")
        assert result == []

    async def test_returns_empty_for_no_data(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []
        with patch("src.core.memory.session_buffer.redis", mock_redis):
            result = await get_session_buffer("user-1")
        assert result == []


class TestUpdateSessionBuffer:
    async def test_pushes_and_sets_ttl(self):
        mock_redis = AsyncMock()
        with patch("src.core.memory.session_buffer.redis", mock_redis):
            await update_session_buffer("user-1", "salary 6000", "income")
        key = f"{REDIS_KEY_PREFIX}:user-1"
        mock_redis.rpush.assert_called_once()
        push_args = mock_redis.rpush.call_args
        assert push_args[0][0] == key
        entry = json.loads(push_args[0][1])
        assert entry["fact"] == "salary 6000"
        assert entry["category"] == "income"
        mock_redis.ltrim.assert_called_once_with(key, -MAX_BUFFER_ITEMS, -1)
        mock_redis.expire.assert_called_once_with(key, SESSION_BUFFER_TTL)

    async def test_graceful_on_redis_failure(self):
        mock_redis = AsyncMock()
        mock_redis.rpush.side_effect = Exception("Redis down")
        with patch("src.core.memory.session_buffer.redis", mock_redis):
            # Should not raise
            await update_session_buffer("user-1", "test fact")


class TestClearSessionBuffer:
    async def test_deletes_key(self):
        mock_redis = AsyncMock()
        with patch("src.core.memory.session_buffer.redis", mock_redis):
            await clear_session_buffer("user-1")
        mock_redis.delete.assert_called_once_with(f"{REDIS_KEY_PREFIX}:user-1")

    async def test_graceful_on_redis_failure(self):
        mock_redis = AsyncMock()
        mock_redis.delete.side_effect = Exception("Redis down")
        with patch("src.core.memory.session_buffer.redis", mock_redis):
            await clear_session_buffer("user-1")


class TestFormatBufferBlock:
    def test_empty_returns_empty(self):
        assert format_buffer_block([]) == ""

    def test_formats_facts(self):
        facts = [
            {"fact": "salary 6000", "category": "income"},
            {"fact": "budget groceries 500", "category": "budget_limit"},
        ]
        result = format_buffer_block(facts)
        assert "Новая информация" in result
        assert "- salary 6000" in result
        assert "- budget groceries 500" in result

    def test_skips_empty_facts(self):
        facts = [{"fact": "", "category": ""}, {"fact": "real fact", "category": ""}]
        result = format_buffer_block(facts)
        assert "- real fact" in result
        assert result.count("- ") == 1

    def test_no_facts_with_content_returns_empty(self):
        facts = [{"category": "income"}]  # no "fact" key
        assert format_buffer_block(facts) == ""


class TestConstants:
    def test_ttl_is_30_minutes(self):
        assert SESSION_BUFFER_TTL == 1800

    def test_max_buffer_items(self):
        assert MAX_BUFFER_ITEMS == 20

    def test_redis_key_prefix(self):
        assert REDIS_KEY_PREFIX == "session_facts"
