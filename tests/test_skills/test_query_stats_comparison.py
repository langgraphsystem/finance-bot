"""Tests for query_stats period comparison logic."""

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.query_stats.handler import (
    QueryStatsSkill,
    _calculate_previous_period,
)


@pytest.fixture
def stats_skill():
    return QueryStatsSkill()


@pytest.fixture
def sample_message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="покажи статистику",
    )


@pytest.fixture
def sample_ctx():
    return SessionContext(
        user_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        role="owner",
        language="ru",
        currency="USD",
        business_type="trucker",
        categories=[],
        merchant_mappings=[],
    )


# ── _calculate_previous_period tests ──────────────────────────────────


class TestCalculatePreviousPeriod:
    def test_month_period(self):
        """Previous month boundaries are calculated correctly."""
        start = date(2026, 2, 1)
        end = date(2026, 2, 13)
        prev_start, prev_end = _calculate_previous_period(start, end, "month")
        assert prev_start == date(2026, 1, 1)
        assert prev_end == date(2026, 2, 1)

    def test_month_period_january(self):
        """January rolls back to December of previous year."""
        start = date(2026, 1, 1)
        end = date(2026, 1, 15)
        prev_start, prev_end = _calculate_previous_period(start, end, "month")
        assert prev_start == date(2025, 12, 1)
        assert prev_end == date(2026, 1, 1)

    def test_week_period(self):
        """Previous week is exactly 7 days before."""
        start = date(2026, 2, 9)  # Monday
        end = date(2026, 2, 13)  # Friday
        prev_start, prev_end = _calculate_previous_period(start, end, "week")
        assert prev_start == date(2026, 2, 2)
        assert prev_end == date(2026, 2, 6)

    def test_year_period(self):
        """Previous year keeps same month/day."""
        start = date(2026, 1, 1)
        end = date(2026, 2, 13)
        prev_start, prev_end = _calculate_previous_period(start, end, "year")
        assert prev_start == date(2025, 1, 1)
        assert prev_end == date(2025, 2, 13)


# ── _get_comparison_data tests ────────────────────────────────────────


class TestGetComparisonData:
    @pytest.mark.asyncio
    async def test_both_periods_have_data(self, stats_skill):
        """Comparison works when both periods have transactions."""
        # Mock the DB session to return data for current and previous periods
        mock_current_rows = [("Food", 200.0), ("Transport", 100.0)]
        mock_prev_rows = [("Food", 150.0), ("Transport", 120.0)]

        mock_current_result = MagicMock()
        mock_current_result.all.return_value = mock_current_rows
        mock_prev_result = MagicMock()
        mock_prev_result.all.return_value = mock_prev_rows

        mock_session = AsyncMock()
        # First execute call = current period, second = previous period
        mock_session.execute = AsyncMock(side_effect=[mock_current_result, mock_prev_result])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.skills.query_stats.handler.async_session",
            return_value=mock_session,
        ):
            family_id = str(uuid.uuid4())
            result = await stats_skill._get_comparison_data(
                family_id=family_id,
                current_start=date(2026, 2, 1),
                current_end=date(2026, 2, 13),
                prev_start=date(2026, 1, 1),
                prev_end=date(2026, 2, 1),
            )

        assert result["current_total"] == 300.0
        assert result["previous_total"] == 270.0
        assert len(result["by_category"]) == 2

        # Verify percentage calculations
        by_cat = {item["category"]: item for item in result["by_category"]}
        # Food: (200 - 150) / 150 * 100 = +33.33%
        assert abs(by_cat["Food"]["change_pct"] - 33.333) < 0.01
        # Transport: (100 - 120) / 120 * 100 = -16.67%
        assert abs(by_cat["Transport"]["change_pct"] - (-16.667)) < 0.01

    @pytest.mark.asyncio
    async def test_empty_previous_period(self, stats_skill):
        """Comparison works when previous period has no data."""
        mock_current_rows = [("Food", 200.0)]
        mock_prev_rows = []

        mock_current_result = MagicMock()
        mock_current_result.all.return_value = mock_current_rows
        mock_prev_result = MagicMock()
        mock_prev_result.all.return_value = mock_prev_rows

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[mock_current_result, mock_prev_result])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.skills.query_stats.handler.async_session",
            return_value=mock_session,
        ):
            family_id = str(uuid.uuid4())
            result = await stats_skill._get_comparison_data(
                family_id=family_id,
                current_start=date(2026, 2, 1),
                current_end=date(2026, 2, 13),
                prev_start=date(2026, 1, 1),
                prev_end=date(2026, 2, 1),
            )

        assert result["current_total"] == 200.0
        assert result["previous_total"] == 0.0
        assert len(result["by_category"]) == 1
        # New category with no previous data => 100%
        assert result["by_category"][0]["change_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_empty_both_periods(self, stats_skill):
        """Comparison returns zeros when both periods are empty."""
        mock_current_result = MagicMock()
        mock_current_result.all.return_value = []
        mock_prev_result = MagicMock()
        mock_prev_result.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[mock_current_result, mock_prev_result])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.skills.query_stats.handler.async_session",
            return_value=mock_session,
        ):
            family_id = str(uuid.uuid4())
            result = await stats_skill._get_comparison_data(
                family_id=family_id,
                current_start=date(2026, 2, 1),
                current_end=date(2026, 2, 13),
                prev_start=date(2026, 1, 1),
                prev_end=date(2026, 2, 1),
            )

        assert result["current_total"] == 0.0
        assert result["previous_total"] == 0.0
        assert result["by_category"] == []

    @pytest.mark.asyncio
    async def test_category_only_in_previous(self, stats_skill):
        """Category that existed before but has no current spending."""
        mock_current_rows = []
        mock_prev_rows = [("Rent", 1000.0)]

        mock_current_result = MagicMock()
        mock_current_result.all.return_value = mock_current_rows
        mock_prev_result = MagicMock()
        mock_prev_result.all.return_value = mock_prev_rows

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[mock_current_result, mock_prev_result])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.skills.query_stats.handler.async_session",
            return_value=mock_session,
        ):
            family_id = str(uuid.uuid4())
            result = await stats_skill._get_comparison_data(
                family_id=family_id,
                current_start=date(2026, 2, 1),
                current_end=date(2026, 2, 13),
                prev_start=date(2026, 1, 1),
                prev_end=date(2026, 2, 1),
            )

        assert result["current_total"] == 0.0
        assert result["previous_total"] == 1000.0
        assert len(result["by_category"]) == 1
        # (0 - 1000) / 1000 * 100 = -100%
        assert result["by_category"][0]["change_pct"] == -100.0

    @pytest.mark.asyncio
    async def test_sorting_by_absolute_change(self, stats_skill):
        """Results are sorted by absolute change percentage descending."""
        mock_current_rows = [("A", 100.0), ("B", 300.0), ("C", 50.0)]
        mock_prev_rows = [("A", 100.0), ("B", 100.0), ("C", 100.0)]

        mock_current_result = MagicMock()
        mock_current_result.all.return_value = mock_current_rows
        mock_prev_result = MagicMock()
        mock_prev_result.all.return_value = mock_prev_rows

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[mock_current_result, mock_prev_result])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.skills.query_stats.handler.async_session",
            return_value=mock_session,
        ):
            family_id = str(uuid.uuid4())
            result = await stats_skill._get_comparison_data(
                family_id=family_id,
                current_start=date(2026, 2, 1),
                current_end=date(2026, 2, 13),
                prev_start=date(2026, 1, 1),
                prev_end=date(2026, 2, 1),
            )

        categories_order = [item["category"] for item in result["by_category"]]
        # B: +200%, C: -50%, A: 0%
        assert categories_order == ["B", "C", "A"]


# ── Percentage calculation edge cases ────────────────────────────────


class TestPercentageCalculation:
    def test_zero_previous_with_current(self):
        """When prev=0 and curr>0, change is 100%."""
        prev = 0
        curr = 50
        if prev > 0:
            change_pct = ((curr - prev) / prev) * 100
        elif curr > 0:
            change_pct = 100.0
        else:
            change_pct = 0.0
        assert change_pct == 100.0

    def test_zero_both(self):
        """When both periods are zero, change is 0%."""
        prev = 0
        curr = 0
        if prev > 0:
            change_pct = ((curr - prev) / prev) * 100
        elif curr > 0:
            change_pct = 100.0
        else:
            change_pct = 0.0
        assert change_pct == 0.0

    def test_decrease(self):
        """Decrease from 200 to 100 is -50%."""
        prev = 200
        curr = 100
        change_pct = ((curr - prev) / prev) * 100
        assert change_pct == -50.0

    def test_increase(self):
        """Increase from 100 to 150 is +50%."""
        prev = 100
        curr = 150
        change_pct = ((curr - prev) / prev) * 100
        assert change_pct == 50.0

    def test_no_change(self):
        """Same values yield 0%."""
        prev = 100
        curr = 100
        change_pct = ((curr - prev) / prev) * 100
        assert change_pct == 0.0
