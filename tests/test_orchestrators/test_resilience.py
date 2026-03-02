"""Tests for orchestrator resilience: timeout, retry, DLQ."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrators.resilience import (
    _sanitize_state,
    save_to_dlq,
    with_retry,
    with_timeout,
)

# ---------------------------------------------------------------------------
# with_timeout
# ---------------------------------------------------------------------------


class TestWithTimeout:
    async def test_completes_within_timeout(self):
        @with_timeout(5)
        async def fast_node(state):
            return {"result": "ok"}

        result = await fast_node({"input": "x"})
        assert result == {"result": "ok"}

    async def test_raises_on_timeout(self):
        @with_timeout(0.05)
        async def slow_node(state):
            await asyncio.sleep(1)
            return {"result": "never"}

        with pytest.raises(asyncio.TimeoutError):
            await slow_node({})

    async def test_preserves_function_name(self):
        @with_timeout(5)
        async def my_node(state):
            return {}

        assert my_node.__name__ == "my_node"


# ---------------------------------------------------------------------------
# with_retry
# ---------------------------------------------------------------------------


class TestWithRetry:
    async def test_succeeds_on_first_try(self):
        call_count = 0

        @with_retry(max_retries=2, backoff_base=0.01)
        async def reliable_node(state):
            nonlocal call_count
            call_count += 1
            return {"ok": True}

        result = await reliable_node({})
        assert result == {"ok": True}
        assert call_count == 1

    async def test_retries_on_failure(self):
        call_count = 0

        @with_retry(max_retries=2, backoff_base=0.01)
        async def flaky_node(state):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return {"ok": True}

        result = await flaky_node({})
        assert result == {"ok": True}
        assert call_count == 3

    async def test_exhausts_retries(self):
        call_count = 0

        @with_retry(max_retries=1, backoff_base=0.01)
        async def broken_node(state):
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            await broken_node({})
        assert call_count == 2  # 1 initial + 1 retry

    async def test_exponential_backoff(self):
        """Verify delays grow exponentially."""
        delays = []
        original_sleep = asyncio.sleep

        async def mock_sleep(seconds):
            delays.append(seconds)
            await original_sleep(0)  # don't actually wait

        @with_retry(max_retries=3, backoff_base=1.0)
        async def always_fails(state):
            raise RuntimeError("fail")

        with patch("src.orchestrators.resilience.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(RuntimeError):
                await always_fails({})

        assert len(delays) == 3
        assert delays[0] == 1.0   # 1 * 2^0
        assert delays[1] == 2.0   # 1 * 2^1
        assert delays[2] == 4.0   # 1 * 2^2

    async def test_preserves_function_name(self):
        @with_retry(max_retries=1)
        async def my_node(state):
            return {}

        assert my_node.__name__ == "my_node"


# ---------------------------------------------------------------------------
# with_timeout + with_retry combined
# ---------------------------------------------------------------------------


class TestCombined:
    async def test_timeout_triggers_retry(self):
        call_count = 0

        @with_retry(max_retries=1, backoff_base=0.01)
        @with_timeout(0.05)
        async def slow_then_fast(state):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(1)
            return {"ok": True}

        result = await slow_then_fast({})
        assert result == {"ok": True}
        assert call_count == 2


# ---------------------------------------------------------------------------
# save_to_dlq
# ---------------------------------------------------------------------------


class TestSaveToDlq:
    async def test_saves_to_database(self):
        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.core.db.async_session", return_value=mock_ctx):
            result = await save_to_dlq(
                graph_name="email",
                thread_id="email-123-send_email-456",
                user_id="00000000-0000-0000-0000-000000000001",
                family_id="00000000-0000-0000-0000-000000000002",
                error="TimeoutError: node timed out",
                state={"intent": "send_email", "draft_body": "Hello"},
            )

        assert result is not None
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    async def test_handles_db_failure_gracefully(self):
        with patch(
            "src.core.db.async_session",
            side_effect=Exception("DB down"),
        ):
            result = await save_to_dlq(
                graph_name="email",
                thread_id="t1",
                user_id="00000000-0000-0000-0000-000000000001",
                family_id="00000000-0000-0000-0000-000000000002",
                error="some error",
            )
        assert result is None


# ---------------------------------------------------------------------------
# _sanitize_state
# ---------------------------------------------------------------------------


class TestSanitizeState:
    def test_none_input(self):
        assert _sanitize_state(None) is None

    def test_removes_dunder_keys(self):
        result = _sanitize_state({"__interrupt__": [], "intent": "send"})
        assert "__interrupt__" not in result
        assert result["intent"] == "send"

    def test_serializable_values_preserved(self):
        state = {"a": "str", "b": 42, "c": True, "d": None, "e": [1, 2]}
        result = _sanitize_state(state)
        assert result == state

    def test_non_serializable_converted_to_string(self):
        state = {"obj": object()}
        result = _sanitize_state(state)
        assert isinstance(result["obj"], str)
