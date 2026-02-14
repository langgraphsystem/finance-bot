"""Tests for query_stats period comparison logic."""

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.gateway.types import IncomingMessage, MessageType
from src.skills.query_stats.handler import (
    QueryStatsSkill,
    _calculate_previous_period,
    _resolve_period,
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
        """Previous week is exactly 7 days before start."""
        start = date(2026, 2, 9)  # Monday
        end = date(2026, 2, 14)  # Saturday (exclusive)
        prev_start, prev_end = _calculate_previous_period(start, end, "week")
        assert prev_start == date(2026, 2, 2)
        assert prev_end == date(2026, 2, 9)

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


# ── _resolve_period tests ──────────────────────────────────────────


class TestResolvePeriod:
    def test_today(self):
        """period=today returns today only."""
        start, end, label = _resolve_period({"period": "today"})
        today = date.today()
        assert start == today
        assert end == today + timedelta(days=1)
        assert label == "сегодня"

    def test_day_with_date(self):
        """period=day with specific date."""
        start, end, label = _resolve_period({"period": "day", "date": "2026-02-10"})
        assert start == date(2026, 2, 10)
        assert end == date(2026, 2, 11)
        assert "10.02.2026" in label

    def test_day_without_date_falls_back_to_today(self):
        """period=day without date uses today."""
        start, end, _ = _resolve_period({"period": "day"})
        today = date.today()
        assert start == today

    def test_week(self):
        """period=week returns Monday to today+1."""
        start, end, label = _resolve_period({"period": "week"})
        today = date.today()
        assert start == today - timedelta(days=today.weekday())
        assert label == "эту неделю"

    def test_prev_week(self):
        """period=prev_week returns previous Mon-Sun."""
        start, end, label = _resolve_period({"period": "prev_week"})
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        assert end == this_monday
        assert start == this_monday - timedelta(days=7)
        assert label == "прошлую неделю"

    def test_month(self):
        """period=month returns 1st of month to today+1."""
        start, end, label = _resolve_period({"period": "month"})
        today = date.today()
        assert start == today.replace(day=1)
        assert label == "этот месяц"

    def test_prev_month(self):
        """period=prev_month returns previous month boundaries."""
        start, end, label = _resolve_period({"period": "prev_month"})
        today = date.today()
        assert end == today.replace(day=1)
        assert label == "прошлый месяц"

    def test_year(self):
        """period=year returns Jan 1 to today+1."""
        start, end, label = _resolve_period({"period": "year"})
        today = date.today()
        assert start == date(today.year, 1, 1)
        assert label == "этот год"

    def test_custom_range(self):
        """period=custom with date_from and date_to."""
        start, end, label = _resolve_period(
            {
                "period": "custom",
                "date_from": "2026-01-15",
                "date_to": "2026-02-10",
            }
        )
        assert start == date(2026, 1, 15)
        assert end == date(2026, 2, 11)  # exclusive
        assert "15.01" in label
        assert "10.02" in label

    def test_custom_only_date_from(self):
        """period=custom with only date_from."""
        start, end, label = _resolve_period(
            {
                "period": "custom",
                "date_from": "2026-01-01",
            }
        )
        assert start == date(2026, 1, 1)
        assert "01.01.2026" in label

    def test_none_period_defaults_to_month(self):
        """No period specified defaults to current month."""
        start, end, label = _resolve_period({})
        today = date.today()
        assert start == today.replace(day=1)
        assert label == "этот месяц"

    def test_null_period_defaults_to_month(self):
        """period=None defaults to current month."""
        start, end, label = _resolve_period({"period": None})
        today = date.today()
        assert start == today.replace(day=1)


# ── _calculate_previous_period — new period types ──────────────────


class TestCalculatePreviousPeriodExtended:
    def test_today_period(self):
        """Previous period for today = yesterday."""
        today = date.today()
        start = today
        end = today + timedelta(days=1)
        prev_start, prev_end = _calculate_previous_period(start, end, "today")
        assert prev_start == today - timedelta(days=1)
        assert prev_end == today

    def test_day_period(self):
        """Previous period for a specific day = the day before."""
        d = date(2026, 2, 10)
        start = d
        end = d + timedelta(days=1)
        prev_start, prev_end = _calculate_previous_period(start, end, "day")
        assert prev_start == date(2026, 2, 9)
        assert prev_end == date(2026, 2, 10)

    def test_custom_period(self):
        """Previous period for custom range has same duration."""
        start = date(2026, 1, 15)
        end = date(2026, 2, 15)
        prev_start, prev_end = _calculate_previous_period(start, end, "custom")
        assert prev_end == start
        assert (end - start) == (start - prev_start)
