"""Tests for dialog_history skill."""

import sys
import types
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

for module_name in (
    "psycopg_pool",
    "psycopg",
    "psycopg.pq",
    "mem0",
    "mem0.vector_stores",
    "mem0.vector_stores.pgvector",
):
    if module_name not in sys.modules:
        sys.modules[module_name] = types.ModuleType(module_name)

pool_mod = sys.modules["psycopg_pool"]
if not hasattr(pool_mod, "ConnectionPool"):
    pool_mod.ConnectionPool = object  # type: ignore[attr-defined]

mem0_mod = sys.modules["mem0"]
if not hasattr(mem0_mod, "Memory"):
    mem0_mod.Memory = MagicMock  # type: ignore[attr-defined]

from src.core.context import SessionContext  # noqa: E402
from src.skills.dialog_history.handler import (  # noqa: E402
    _detect_period,
    _period_bounds,
    skill,
)


@pytest.fixture
def ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="RUB",
        business_type=None,
        categories=[],
        merchant_mappings=[],
        timezone="UTC",
    )


@pytest.fixture
def message():
    msg = MagicMock()
    msg.text = "о чём мы говорили на этой неделе?"
    return msg


class TestDetectPeriod:
    def test_yesterday_ru(self):
        assert _detect_period("о чём мы говорили вчера?") == "yesterday"

    def test_yesterday_en(self):
        assert _detect_period("what did we discuss yesterday?") == "yesterday"

    def test_week_ru(self):
        assert _detect_period("о чём мы говорили на этой неделе?") == "week"

    def test_week_en(self):
        assert _detect_period("show me this week's conversations") == "week"

    def test_month_ru(self):
        assert _detect_period("что обсуждали в этом месяце?") == "month"

    def test_today_ru(self):
        assert _detect_period("что мы обсуждали сегодня?") == "today"

    def test_default_is_week(self):
        assert _detect_period("о чём мы говорили?") == "week"


class TestPeriodBounds:
    def test_today_uses_tz_aware_utc_start(self):
        start_at, end_at = _period_bounds("today", "America/Chicago")

        assert start_at.tzinfo is UTC
        assert end_at is None

    def test_yesterday_returns_closed_open_window(self):
        start_at, end_at = _period_bounds("yesterday", "UTC")

        assert start_at.tzinfo is UTC
        assert end_at is not None
        assert end_at.tzinfo is UTC
        assert end_at - start_at == timedelta(days=1)

    def test_unknown_timezone_falls_back_to_utc(self):
        start_at, end_at = _period_bounds("week", "Mars/Olympus")

        assert start_at.tzinfo is UTC
        assert end_at is None


class TestDialogHistorySkill:
    def test_skill_metadata(self):
        assert skill.name == "dialog_history"
        assert "dialog_history" in skill.intents
        assert skill.model == "gemini-3.1-flash-lite-preview"

    async def test_returns_summaries_when_found(self, ctx, message):
        from unittest.mock import patch

        mock_summary = MagicMock()
        mock_summary.summary = "Обсуждали бюджет на аренду и расходы на кофе"
        mock_summary.created_at = datetime.now(UTC)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_summary]
        mock_session.execute.return_value = mock_result

        mock_ctx_mgr = AsyncMock()
        mock_ctx_mgr.__aenter__.return_value = mock_session
        mock_ctx_mgr.__aexit__.return_value = False

        with patch("src.core.db.async_session", return_value=mock_ctx_mgr):
            result = await skill.execute(message, ctx)

        assert result.response_text
        assert "Обсуждали бюджет" in result.response_text

    async def test_yesterday_uses_exclusive_upper_bound(self, ctx):
        from unittest.mock import patch

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        mock_ctx_mgr = AsyncMock()
        mock_ctx_mgr.__aenter__.return_value = mock_session
        mock_ctx_mgr.__aexit__.return_value = False

        msg = MagicMock()
        msg.text = "о чём мы говорили вчера?"

        with patch("src.core.db.async_session", return_value=mock_ctx_mgr):
            result = await skill.execute(msg, ctx)

        query = mock_session.execute.await_args.args[0]
        compiled = str(query)

        assert "created_at >=" in compiled
        assert "created_at <" in compiled
        assert result.response_text
        assert (
            "вчера" in result.response_text.lower()
            or "yesterday" in result.response_text.lower()
        )

    async def test_returns_error_on_db_failure(self, ctx, message):
        from unittest.mock import patch

        mock_ctx_mgr = AsyncMock()
        mock_ctx_mgr.__aenter__.side_effect = Exception("DB down")

        with patch("src.core.db.async_session", return_value=mock_ctx_mgr):
            result = await skill.execute(message, ctx)

        assert result.response_text
        assert "fail" in result.response_text.lower() or "удалось" in result.response_text

    async def test_truncates_long_summaries(self, ctx, message):
        from unittest.mock import patch

        mock_summary = MagicMock()
        mock_summary.summary = "A" * 500
        mock_summary.created_at = datetime.now(UTC)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_summary]
        mock_session.execute.return_value = mock_result

        mock_ctx_mgr = AsyncMock()
        mock_ctx_mgr.__aenter__.return_value = mock_session
        mock_ctx_mgr.__aexit__.return_value = False

        with patch("src.core.db.async_session", return_value=mock_ctx_mgr):
            result = await skill.execute(message, ctx)

        assert "A" * 201 not in result.response_text
        assert "A" * 200 in result.response_text

    async def test_ru_language_no_history_uses_russian_text(self):
        from unittest.mock import patch

        ctx_ru = SessionContext(
            user_id=str(uuid.uuid4()),
            family_id=str(uuid.uuid4()),
            role="owner",
            language="ru",
            currency="RUB",
            business_type=None,
            categories=[],
            merchant_mappings=[],
            timezone="UTC",
        )
        msg = MagicMock()
        msg.text = "о чём мы говорили?"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_ctx_mgr = AsyncMock()
        mock_ctx_mgr.__aenter__.return_value = mock_session
        mock_ctx_mgr.__aexit__.return_value = False

        with patch("src.core.db.async_session", return_value=mock_ctx_mgr):
            result = await skill.execute(msg, ctx_ru)

        assert "Нет" in result.response_text
