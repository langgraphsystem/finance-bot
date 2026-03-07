"""Tests for dialog_history skill."""

# Stub heavy imports that require system libraries (psycopg, libpq)
# before any src.skills.* import triggers src/skills/__init__.py
import sys
import types
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ------------------------------------------------------------------
# Minimal stubs so that the skill registry can be imported without
# a real psycopg / libpq installation in the local dev environment.
# ------------------------------------------------------------------
for _mod_name in (
    "psycopg_pool",
    "psycopg",
    "psycopg.pq",
    "mem0",
    "mem0.vector_stores",
    "mem0.vector_stores.pgvector",
):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = types.ModuleType(_mod_name)

# Also stub psycopg_pool.ConnectionPool used by mem0_client patch
_pool_mod = sys.modules["psycopg_pool"]
if not hasattr(_pool_mod, "ConnectionPool"):
    _pool_mod.ConnectionPool = object  # type: ignore[attr-defined]

# Stub mem0.Memory
_mem0_mod = sys.modules["mem0"]
if not hasattr(_mem0_mod, "Memory"):
    _mem0_mod.Memory = MagicMock  # type: ignore[attr-defined]

# ------------------------------------------------------------------

from src.core.context import SessionContext  # noqa: E402
from src.skills.dialog_history.handler import (  # noqa: E402
    _detect_period,
    _period_to_date,
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
    )


@pytest.fixture
def message():
    m = MagicMock()
    m.text = "о чём мы говорили на этой неделе?"
    return m


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


class TestPeriodToDate:
    def test_today(self):
        from datetime import date

        assert _period_to_date("today") == date.today()

    def test_yesterday(self):
        from datetime import date, timedelta

        assert _period_to_date("yesterday") == date.today() - timedelta(days=1)

    def test_week(self):
        from datetime import date, timedelta

        assert _period_to_date("week") == date.today() - timedelta(weeks=1)

    def test_month(self):
        from datetime import date, timedelta

        assert _period_to_date("month") == date.today() - timedelta(days=30)

    def test_unknown_defaults_to_week(self):
        from datetime import date, timedelta

        assert _period_to_date("unknown") == date.today() - timedelta(weeks=1)


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

    async def test_returns_no_history_message_when_empty(self, ctx):
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

        assert result.response_text
        assert "yesterday" in result.response_text or "вчера" in result.response_text.lower()

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
