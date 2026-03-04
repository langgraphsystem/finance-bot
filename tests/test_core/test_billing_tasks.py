"""Tests for billing tasks — aggregate_token_stats daily cron."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.tasks.billing_tasks import _log_to_langfuse, aggregate_token_stats


class _FakeRow:
    """Mimics a SQLAlchemy Row for per-model aggregation."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeScalarResult:
    """Mimics scalars().all() for overflow layer query."""

    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class TestAggregateTokenStats:
    async def test_returns_stats_dict(self):
        model_rows = [
            _FakeRow(
                model="claude-sonnet-4-6",
                total_requests=100,
                success_count=95,
                total_tokens_input=500_000,
                total_tokens_output=100_000,
                avg_tokens_input=5000.0,
                avg_duration_ms=450.5,
                cache_hit_count=60,
                total_cache_read=120_000,
                total_cache_creation=30_000,
                total_cost_usd=Decimal("1.500000"),
            ),
            _FakeRow(
                model="gemini-3.1-flash-lite-preview",
                total_requests=200,
                success_count=198,
                total_tokens_input=300_000,
                total_tokens_output=80_000,
                avg_tokens_input=1500.0,
                avg_duration_ms=200.0,
                cache_hit_count=0,
                total_cache_read=0,
                total_cache_creation=0,
                total_cost_usd=Decimal("0.062000"),
            ),
        ]

        overflow_row = _FakeRow(total=300, overflow_count=15)

        overflow_layers = ["mem0,sql", "mem0", "sql", "mem0"]

        # Build mock session
        mock_session = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # per-model query
                result = MagicMock()
                result.all.return_value = model_rows
                return result
            elif call_count == 2:
                # overflow global query
                result = MagicMock()
                result.one.return_value = overflow_row
                return result
            else:
                # overflow layers query
                return _FakeScalarResult(overflow_layers)

        mock_session.execute = mock_execute

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.core.tasks.billing_tasks.async_session",
                return_value=mock_session_ctx,
            ),
            patch("src.core.tasks.billing_tasks._log_to_langfuse"),
        ):
            stats = await aggregate_token_stats()

        assert stats["total_requests"] == 300
        assert stats["overflow_frequency"] == 0.05  # 15/300
        assert stats["overflow_layer_counts"]["mem0"] == 3
        assert stats["overflow_layer_counts"]["sql"] == 2

        claude = stats["models"]["claude-sonnet-4-6"]
        assert claude["total_requests"] == 100
        assert claude["success_rate"] == 0.95
        assert claude["cache_hit_ratio"] == 0.6
        assert claude["total_tokens_input"] == 500_000
        assert claude["total_cost_usd"] == 1.5

        gemini = stats["models"]["gemini-3.1-flash-lite-preview"]
        assert gemini["cache_hit_ratio"] == 0.0
        assert gemini["total_requests"] == 200

    async def test_empty_period(self):
        """No usage logs in the past 24h — returns zeroes."""
        mock_session = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                result = MagicMock()
                result.all.return_value = []
                return result
            elif call_count == 2:
                result = MagicMock()
                result.one.return_value = _FakeRow(total=0, overflow_count=0)
                return result
            else:
                return _FakeScalarResult([])

        mock_session.execute = mock_execute
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.core.tasks.billing_tasks.async_session",
                return_value=mock_session_ctx,
            ),
            patch("src.core.tasks.billing_tasks._log_to_langfuse"),
        ):
            stats = await aggregate_token_stats()

        assert stats["total_requests"] == 0
        assert stats["overflow_frequency"] == 0
        assert stats["models"] == {}
        assert stats["overflow_layer_counts"] == {}

    async def test_single_model_no_overflow(self):
        """Single model, no overflow layers dropped."""
        model_rows = [
            _FakeRow(
                model="gpt-5.2",
                total_requests=50,
                success_count=50,
                total_tokens_input=100_000,
                total_tokens_output=25_000,
                avg_tokens_input=2000.0,
                avg_duration_ms=300.0,
                cache_hit_count=10,
                total_cache_read=5000,
                total_cache_creation=0,
                total_cost_usd=Decimal("0.875000"),
            ),
        ]

        mock_session = AsyncMock()
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                result = MagicMock()
                result.all.return_value = model_rows
                return result
            elif call_count == 2:
                result = MagicMock()
                result.one.return_value = _FakeRow(total=50, overflow_count=0)
                return result
            else:
                return _FakeScalarResult([])

        mock_session.execute = mock_execute
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.core.tasks.billing_tasks.async_session",
                return_value=mock_session_ctx,
            ),
            patch("src.core.tasks.billing_tasks._log_to_langfuse"),
        ):
            stats = await aggregate_token_stats()

        assert stats["total_requests"] == 50
        assert stats["overflow_frequency"] == 0.0
        gpt = stats["models"]["gpt-5.2"]
        assert gpt["success_rate"] == 1.0
        assert gpt["cache_hit_ratio"] == 0.2


def _empty_stats() -> dict:
    return {
        "total_requests": 0,
        "overflow_frequency": 0,
        "overflow_layer_counts": {},
        "models": {},
    }


class TestLogToLangfuse:
    def test_logs_when_langfuse_available(self):
        mock_langfuse = MagicMock()

        with patch(
            "src.core.observability.get_langfuse",
            return_value=mock_langfuse,
        ):
            _log_to_langfuse({
                "total_requests": 100,
                "overflow_frequency": 0.05,
                "overflow_layer_counts": {"mem0": 3},
                "models": {"claude-sonnet-4-6": {"cache_hit_ratio": 0.6}},
            })

        mock_langfuse.trace.assert_called_once()
        call_kwargs = mock_langfuse.trace.call_args.kwargs
        assert call_kwargs["name"] == "daily_token_stats"
        assert call_kwargs["metadata"]["total_requests"] == 100

    def test_noop_when_langfuse_unavailable(self):
        with patch(
            "src.core.observability.get_langfuse",
            return_value=None,
        ):
            # Should not raise
            _log_to_langfuse(_empty_stats())

    def test_handles_langfuse_error(self):
        with patch(
            "src.core.observability.get_langfuse",
            side_effect=Exception("Langfuse down"),
        ):
            # Should not raise
            _log_to_langfuse(_empty_stats())
