"""Tests for sliding window short-term memory."""

import json
from unittest.mock import AsyncMock, patch

from src.core.memory.sliding_window import (
    DEFAULT_WINDOW_SIZE,
    REDIS_KEY_PREFIX,
    TTL_SECONDS,
    add_message,
    clear_messages,
    count_recent_intents,
    get_recent_messages,
)


class TestAddMessage:
    async def test_pushes_and_sets_ttl(self):
        mock_redis = AsyncMock()
        with patch("src.core.memory.sliding_window.redis", mock_redis):
            await add_message("user-1", "user", "hello", "general_chat")

        key = f"{REDIS_KEY_PREFIX}:user-1:messages"
        mock_redis.rpush.assert_called_once()
        push_args = mock_redis.rpush.call_args
        assert push_args[0][0] == key
        payload = json.loads(push_args[0][1])
        assert payload == {
            "role": "user",
            "content": "hello",
            "intent": "general_chat",
        }
        mock_redis.ltrim.assert_called_once_with(key, -DEFAULT_WINDOW_SIZE, -1)
        mock_redis.expire.assert_called_once_with(key, TTL_SECONDS)

    async def test_graceful_on_redis_failure(self):
        mock_redis = AsyncMock()
        mock_redis.rpush.side_effect = Exception("Redis down")
        with patch("src.core.memory.sliding_window.redis", mock_redis):
            await add_message("user-1", "user", "hello", "general_chat")


class TestGetRecentMessages:
    async def test_reads_from_redis_when_available(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [
            json.dumps({"role": "user", "content": "hello", "intent": "general_chat"}),
            json.dumps({"role": "assistant", "content": "hi", "intent": None}),
        ]
        with patch("src.core.memory.sliding_window.redis", mock_redis):
            result = await get_recent_messages("user-1", limit=2)

        assert result == [
            {"role": "user", "content": "hello", "intent": "general_chat"},
            {"role": "assistant", "content": "hi", "intent": None},
        ]

    async def test_skips_malformed_redis_entries(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [
            "bad-json",
            json.dumps({"role": "user", "content": "hello", "intent": "general_chat"}),
        ]
        with patch("src.core.memory.sliding_window.redis", mock_redis):
            result = await get_recent_messages("user-1", limit=2)

        assert result == [{"role": "user", "content": "hello", "intent": "general_chat"}]

    async def test_falls_back_when_redis_empty(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []
        with (
            patch("src.core.memory.sliding_window.redis", mock_redis),
            patch(
                "src.core.memory.sliding_window._fallback_from_postgres",
                new_callable=AsyncMock,
                return_value=[{"role": "user", "content": "from-db", "intent": "general_chat"}],
            ) as mock_fallback,
        ):
            result = await get_recent_messages("user-1", limit=2)

        assert result == [{"role": "user", "content": "from-db", "intent": "general_chat"}]
        mock_fallback.assert_awaited_once_with("user-1", 2)


class TestCountRecentIntents:
    async def test_counts_only_last_n_user_messages(self):
        messages = [
            {"role": "user", "content": "u1", "intent": "general_chat"},
            {"role": "assistant", "content": "a1", "intent": None},
            {"role": "user", "content": "u2", "intent": "general_chat"},
            {"role": "assistant", "content": "a2", "intent": None},
            {"role": "user", "content": "u3", "intent": "add_expense"},
            {"role": "assistant", "content": "a3", "intent": None},
            {"role": "user", "content": "u4", "intent": "general_chat"},
        ]
        with patch(
            "src.core.memory.sliding_window.get_recent_messages",
            new_callable=AsyncMock,
            return_value=messages,
        ):
            count = await count_recent_intents("user-1", "general_chat", last_n=3)

        assert count == 2


class TestClearMessages:
    async def test_deletes_key(self):
        mock_redis = AsyncMock()
        with patch("src.core.memory.sliding_window.redis", mock_redis):
            await clear_messages("user-1")

        mock_redis.delete.assert_called_once_with(f"{REDIS_KEY_PREFIX}:user-1:messages")

    async def test_graceful_on_redis_failure(self):
        mock_redis = AsyncMock()
        mock_redis.delete.side_effect = Exception("Redis down")
        with patch("src.core.memory.sliding_window.redis", mock_redis):
            await clear_messages("user-1")
