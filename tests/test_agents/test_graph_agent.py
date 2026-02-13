"""Tests for the Pydantic AI graph workflow agent."""

import os
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set test environment before importing app modules
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("APP_ENV", "testing")

from src.agents.graph_agent import (
    FinancialInsight,
    _fallback_analysis,
    get_budget_status,
    get_monthly_spending,
    get_spending_trend,
    run_complex_query,
)


FAMILY_ID = str(uuid.uuid4())


# --- Fixtures ---


@pytest.fixture
def mock_async_session():
    """Create a mock async session context manager."""
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


# --- Tests: FinancialInsight model validation ---


class TestFinancialInsightModel:
    def test_minimal_valid(self):
        insight = FinancialInsight(summary="Test summary")
        assert insight.summary == "Test summary"
        assert insight.metrics == {}
        assert insight.recommendations == []
        assert insight.chart_data is None

    def test_full_valid(self):
        insight = FinancialInsight(
            summary="Расходы за месяц: $500",
            metrics={"total_expense": 500, "total_income": 1000},
            recommendations=["Сократите расходы на еду"],
            chart_data={"categories": {"Еда": 200, "Транспорт": 300}},
        )
        assert insight.summary == "Расходы за месяц: $500"
        assert insight.metrics["total_expense"] == 500
        assert len(insight.recommendations) == 1
        assert insight.chart_data is not None

    def test_default_factories(self):
        insight = FinancialInsight(summary="Test")
        assert isinstance(insight.metrics, dict)
        assert isinstance(insight.recommendations, list)


# --- Tests: get_monthly_spending ---


class TestGetMonthlySpending:
    @pytest.mark.asyncio
    async def test_returns_spending_by_category(self, mock_async_session):
        ctx, session = mock_async_session

        # Mock expense query result
        expense_row_1 = MagicMock()
        expense_row_1.__getitem__ = lambda self, idx: ("Еда", Decimal("200.50"))[idx]
        expense_row_2 = MagicMock()
        expense_row_2.__getitem__ = lambda self, idx: ("Транспорт", Decimal("150.00"))[idx]

        expense_result = MagicMock()
        expense_result.all.return_value = [expense_row_1, expense_row_2]

        # Mock income query result
        income_result = MagicMock()
        income_result.scalar.return_value = Decimal("3000.00")

        session.execute = AsyncMock(side_effect=[expense_result, income_result])

        with patch("src.agents.graph_agent.async_session", return_value=ctx):
            result = await get_monthly_spending(FAMILY_ID, 2026, 2)

        assert result["year"] == 2026
        assert result["month"] == 2
        assert result["total_expense"] == pytest.approx(350.50)
        assert result["total_income"] == pytest.approx(3000.00)
        assert result["by_category"]["Еда"] == pytest.approx(200.50)
        assert result["by_category"]["Транспорт"] == pytest.approx(150.00)

    @pytest.mark.asyncio
    async def test_returns_zeros_when_no_data(self, mock_async_session):
        ctx, session = mock_async_session

        expense_result = MagicMock()
        expense_result.all.return_value = []

        income_result = MagicMock()
        income_result.scalar.return_value = None

        session.execute = AsyncMock(side_effect=[expense_result, income_result])

        with patch("src.agents.graph_agent.async_session", return_value=ctx):
            result = await get_monthly_spending(FAMILY_ID, 2026, 1)

        assert result["total_expense"] == 0
        assert result["total_income"] == 0
        assert result["by_category"] == {}

    @pytest.mark.asyncio
    async def test_december_boundary(self, mock_async_session):
        """Test that December correctly wraps to January of next year."""
        ctx, session = mock_async_session

        expense_result = MagicMock()
        expense_result.all.return_value = []
        income_result = MagicMock()
        income_result.scalar.return_value = None

        session.execute = AsyncMock(side_effect=[expense_result, income_result])

        with patch("src.agents.graph_agent.async_session", return_value=ctx):
            result = await get_monthly_spending(FAMILY_ID, 2025, 12)

        assert result["year"] == 2025
        assert result["month"] == 12


# --- Tests: get_budget_status ---


class TestGetBudgetStatus:
    @pytest.mark.asyncio
    async def test_returns_budget_utilization(self, mock_async_session):
        ctx, session = mock_async_session

        # Mock budget object
        budget = MagicMock()
        budget.period = MagicMock()
        budget.period.value = "monthly"
        budget.period.__eq__ = lambda self, other: str(self.value) == str(other.value)
        budget.amount = Decimal("1000.00")
        budget.category_id = uuid.uuid4()

        budgets_result = MagicMock()
        budgets_result.scalars.return_value = [budget]

        # Mock spending query
        spent_result = MagicMock()
        spent_result.scalar.return_value = Decimal("750.00")

        # Mock category name query
        cat_result = MagicMock()
        cat_result.scalar.return_value = "Еда"

        session.execute = AsyncMock(
            side_effect=[budgets_result, spent_result, cat_result]
        )

        with patch("src.agents.graph_agent.async_session", return_value=ctx):
            result = await get_budget_status(FAMILY_ID)

        assert len(result) == 1
        assert result[0]["category"] == "Еда"
        assert result[0]["limit"] == pytest.approx(1000.00)
        assert result[0]["spent"] == pytest.approx(750.00)
        assert result[0]["percent"] == pytest.approx(75.0)

    @pytest.mark.asyncio
    async def test_empty_budgets(self, mock_async_session):
        ctx, session = mock_async_session

        budgets_result = MagicMock()
        budgets_result.scalars.return_value = []

        session.execute = AsyncMock(return_value=budgets_result)

        with patch("src.agents.graph_agent.async_session", return_value=ctx):
            result = await get_budget_status(FAMILY_ID)

        assert result == []

    @pytest.mark.asyncio
    async def test_budget_without_category(self, mock_async_session):
        """A budget with no category_id should show as 'Общий'."""
        ctx, session = mock_async_session

        budget = MagicMock()
        budget.period = MagicMock()
        budget.period.value = "weekly"
        budget.period.__eq__ = lambda self, other: str(self.value) == str(other.value)
        budget.amount = Decimal("500.00")
        budget.category_id = None

        budgets_result = MagicMock()
        budgets_result.scalars.return_value = [budget]

        spent_result = MagicMock()
        spent_result.scalar.return_value = Decimal("100.00")

        session.execute = AsyncMock(side_effect=[budgets_result, spent_result])

        with patch("src.agents.graph_agent.async_session", return_value=ctx):
            result = await get_budget_status(FAMILY_ID)

        assert len(result) == 1
        assert result[0]["category"] == "Общий"
        assert result[0]["percent"] == pytest.approx(20.0)


# --- Tests: get_spending_trend ---


class TestGetSpendingTrend:
    @pytest.mark.asyncio
    async def test_returns_correct_number_of_months(self):
        """Trend should return data for the requested number of months."""
        mock_spending = AsyncMock(
            return_value={
                "year": 2026,
                "month": 1,
                "total_expense": 100.0,
                "total_income": 200.0,
                "by_category": {},
            }
        )

        with patch("src.agents.graph_agent.get_monthly_spending", mock_spending):
            result = await get_spending_trend(FAMILY_ID, months=3)

        assert len(result) == 3
        assert mock_spending.call_count == 3

    @pytest.mark.asyncio
    async def test_returns_reversed_order(self):
        """Results should be in chronological order (oldest first)."""
        call_order = []

        async def mock_spending(fid, year, month):
            call_order.append((year, month))
            return {
                "year": year,
                "month": month,
                "total_expense": float(month * 100),
                "total_income": 0,
                "by_category": {},
            }

        with patch("src.agents.graph_agent.get_monthly_spending", side_effect=mock_spending):
            result = await get_spending_trend(FAMILY_ID, months=3)

        # Results should be chronologically ordered (earliest first by year-month)
        year_months = [(r["year"], r["month"]) for r in result]
        assert year_months == sorted(year_months)

    @pytest.mark.asyncio
    async def test_single_month(self):
        mock_spending = AsyncMock(
            return_value={
                "year": 2026,
                "month": 2,
                "total_expense": 500.0,
                "total_income": 1000.0,
                "by_category": {"Еда": 500.0},
            }
        )

        with patch("src.agents.graph_agent.get_monthly_spending", mock_spending):
            result = await get_spending_trend(FAMILY_ID, months=1)

        assert len(result) == 1
        assert result[0]["total_expense"] == 500.0


# --- Tests: _fallback_analysis ---


class TestFallbackAnalysis:
    @pytest.mark.asyncio
    async def test_returns_financial_insight(self):
        """Fallback should return a valid FinancialInsight without pydantic-ai."""
        mock_spending = AsyncMock(
            return_value={
                "year": 2026,
                "month": 2,
                "total_expense": 450.0,
                "total_income": 2000.0,
                "by_category": {"Еда": 200.0, "Транспорт": 150.0, "Развлечения": 100.0},
            }
        )
        mock_budgets = AsyncMock(
            return_value=[
                {
                    "category": "Еда",
                    "limit": 300.0,
                    "spent": 200.0,
                    "percent": 66.7,
                    "period": "monthly",
                },
            ]
        )
        mock_trend = AsyncMock(
            return_value=[
                {"month": 12, "total_expense": 400.0, "total_income": 1800.0, "by_category": {}},
                {"month": 1, "total_expense": 420.0, "total_income": 1900.0, "by_category": {}},
                {"month": 2, "total_expense": 450.0, "total_income": 2000.0, "by_category": {}},
            ]
        )

        with (
            patch("src.agents.graph_agent.get_monthly_spending", mock_spending),
            patch("src.agents.graph_agent.get_budget_status", mock_budgets),
            patch("src.agents.graph_agent.get_spending_trend", mock_trend),
        ):
            result = await _fallback_analysis("анализ финансов", FAMILY_ID)

        assert isinstance(result, FinancialInsight)
        assert "$450.00" in result.summary
        assert "$2000.00" in result.summary
        assert result.metrics["total_expense"] == 450.0
        assert result.metrics["total_income"] == 2000.0
        assert result.metrics["balance"] == pytest.approx(1550.0)
        assert result.chart_data is not None
        assert len(result.chart_data["trend"]) == 3

    @pytest.mark.asyncio
    async def test_fallback_with_exceeded_budget(self):
        """Fallback should generate recommendations for exceeded budgets."""
        mock_spending = AsyncMock(
            return_value={
                "year": 2026,
                "month": 2,
                "total_expense": 500.0,
                "total_income": 0,
                "by_category": {"Еда": 500.0},
            }
        )
        mock_budgets = AsyncMock(
            return_value=[
                {
                    "category": "Еда",
                    "limit": 400.0,
                    "spent": 500.0,
                    "percent": 125.0,
                    "period": "monthly",
                },
            ]
        )
        mock_trend = AsyncMock(return_value=[])

        with (
            patch("src.agents.graph_agent.get_monthly_spending", mock_spending),
            patch("src.agents.graph_agent.get_budget_status", mock_budgets),
            patch("src.agents.graph_agent.get_spending_trend", mock_trend),
        ):
            result = await _fallback_analysis("проверь бюджет", FAMILY_ID)

        assert len(result.recommendations) >= 1
        assert "превышен" in result.recommendations[0]

    @pytest.mark.asyncio
    async def test_fallback_with_warning_budget(self):
        """Budgets at 80-99% should generate warning recommendations."""
        mock_spending = AsyncMock(
            return_value={
                "year": 2026,
                "month": 2,
                "total_expense": 400.0,
                "total_income": 0,
                "by_category": {"Еда": 400.0},
            }
        )
        mock_budgets = AsyncMock(
            return_value=[
                {
                    "category": "Еда",
                    "limit": 450.0,
                    "spent": 400.0,
                    "percent": 88.9,
                    "period": "monthly",
                },
            ]
        )
        mock_trend = AsyncMock(return_value=[])

        with (
            patch("src.agents.graph_agent.get_monthly_spending", mock_spending),
            patch("src.agents.graph_agent.get_budget_status", mock_budgets),
            patch("src.agents.graph_agent.get_spending_trend", mock_trend),
        ):
            result = await _fallback_analysis("проверь бюджет", FAMILY_ID)

        assert len(result.recommendations) >= 1
        assert "будьте внимательны" in result.recommendations[0]

    @pytest.mark.asyncio
    async def test_fallback_no_income(self):
        """When income is zero, summary should not mention income."""
        mock_spending = AsyncMock(
            return_value={
                "year": 2026,
                "month": 2,
                "total_expense": 300.0,
                "total_income": 0,
                "by_category": {"Еда": 300.0},
            }
        )
        mock_budgets = AsyncMock(return_value=[])
        mock_trend = AsyncMock(return_value=[])

        with (
            patch("src.agents.graph_agent.get_monthly_spending", mock_spending),
            patch("src.agents.graph_agent.get_budget_status", mock_budgets),
            patch("src.agents.graph_agent.get_spending_trend", mock_trend),
        ):
            result = await _fallback_analysis("расходы", FAMILY_ID)

        assert "Доходы" not in result.summary
        assert "$300.00" in result.summary


# --- Tests: run_complex_query ---


class TestRunComplexQuery:
    @pytest.mark.asyncio
    async def test_fallback_when_pydantic_ai_unavailable(self):
        """run_complex_query should fall back gracefully when pydantic-ai is missing."""
        mock_spending = AsyncMock(
            return_value={
                "year": 2026,
                "month": 2,
                "total_expense": 100.0,
                "total_income": 500.0,
                "by_category": {"Еда": 100.0},
            }
        )
        mock_budgets = AsyncMock(return_value=[])
        mock_trend = AsyncMock(return_value=[])

        with (
            patch("src.agents.graph_agent.get_monthly_spending", mock_spending),
            patch("src.agents.graph_agent.get_budget_status", mock_budgets),
            patch("src.agents.graph_agent.get_spending_trend", mock_trend),
            patch.dict("sys.modules", {"pydantic_ai": None}),
        ):
            result = await run_complex_query("анализ", FAMILY_ID)

        assert isinstance(result, FinancialInsight)
        assert result.summary  # non-empty summary

    @pytest.mark.asyncio
    async def test_fallback_on_agent_exception(self):
        """run_complex_query should fall back on any agent exception."""
        mock_spending = AsyncMock(
            return_value={
                "year": 2026,
                "month": 2,
                "total_expense": 200.0,
                "total_income": 0,
                "by_category": {},
            }
        )
        mock_budgets = AsyncMock(return_value=[])
        mock_trend = AsyncMock(return_value=[])

        mock_agent_cls = MagicMock()
        mock_agent_cls.side_effect = RuntimeError("API key missing")

        mock_pydantic_ai = MagicMock()
        mock_pydantic_ai.Agent = mock_agent_cls

        with (
            patch("src.agents.graph_agent.get_monthly_spending", mock_spending),
            patch("src.agents.graph_agent.get_budget_status", mock_budgets),
            patch("src.agents.graph_agent.get_spending_trend", mock_trend),
            patch.dict("sys.modules", {"pydantic_ai": mock_pydantic_ai}),
        ):
            result = await run_complex_query("что с финансами", FAMILY_ID)

        assert isinstance(result, FinancialInsight)
