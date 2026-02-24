"""Tests for QueryStatsSkill."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.query_stats.handler import _resolve_period, skill

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(category: str, total: float):
    """Create a mock DB row that supports tuple unpacking (name, amount)."""
    row = (category, Decimal(str(total)))
    return row


def _mock_session(stats_rows, total_val=None, income_val=None):
    """Return a factory that yields a mock session handling multiple execute calls.

    Execute call order in the handler:
      1. Category stats  → result.all() → stats_rows
      2. Total expenses  → result.scalar() → total_val
      3. Total income    → result.scalar() → income_val
      4-5. Comparison period queries (wrapped in try/except — safe to fail)
    """
    result_stats = MagicMock()
    result_stats.all.return_value = stats_rows

    result_total = MagicMock()
    result_total.scalar.return_value = total_val

    result_income = MagicMock()
    result_income.scalar.return_value = income_val

    # Comparison queries — return empty (will show no comparison)
    result_empty = MagicMock()
    result_empty.all.return_value = []

    mock_sess = AsyncMock()
    mock_sess.execute = AsyncMock(
        side_effect=[result_stats, result_total, result_income, result_empty, result_empty]
    )

    # Support `async with async_session() as session:`
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_sess)
    ctx.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=ctx)


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="test-1",
        user_id="tg_123",
        chat_id="chat_123",
        type=MessageType.text,
        text=text,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_no_data_returns_message(sample_context):
    """Empty DB results return 'данных не найдено' message."""
    message = _make_message("статистика за месяц")
    intent_data = {"period": "month"}

    with patch(
        "src.skills.query_stats.handler.async_session",
        return_value=_mock_session(stats_rows=[], total_val=None, income_val=None)(),
    ):
        result = await skill.execute(message, sample_context, intent_data)

    assert "данных не найдено" in result.response_text.lower()


async def test_resolve_period_month():
    """Period 'month' resolves to first day of current month."""
    start, end, label = _resolve_period({"period": "month"})

    today = date.today()
    assert start.year == today.year
    assert start.month == today.month
    assert start.day == 1


async def test_resolve_period_week():
    """Period 'week' resolves start to Monday of current week."""
    start, end, label = _resolve_period({"period": "week"})

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    start_date = start.date() if hasattr(start, "date") and callable(start.date) else start
    assert start_date == monday


async def test_stats_with_data_calls_llm(sample_context):
    """When DB has data, generate_text is called to format the response."""
    message = _make_message("траты за месяц")
    intent_data = {"period": "month"}

    rows = [
        _make_row("Дизель", 500.0),
        _make_row("Ремонт", 200.0),
    ]

    with (
        patch(
            "src.skills.query_stats.handler.async_session",
            return_value=_mock_session(
                stats_rows=rows, total_val=Decimal("700"), income_val=None
            )(),
        ),
        patch(
            "src.skills.query_stats.handler.generate_text",
            new_callable=AsyncMock,
            return_value="Статистика: Дизель 500, Ремонт 200",
        ) as mock_llm,
        patch(
            "src.skills.query_stats.handler.create_pie_chart",
            return_value="https://chart.url/pie.png",
        ),
    ):
        await skill.execute(message, sample_context, intent_data)

    mock_llm.assert_called_once()


async def test_chart_generated_with_categories(sample_context):
    """Pie chart is generated when 2+ categories are present."""
    message = _make_message("расходы за неделю")
    intent_data = {"period": "week"}

    rows = [
        _make_row("Дизель", 350.0),
        _make_row("Продукты", 150.0),
        _make_row("Ремонт", 100.0),
    ]

    with (
        patch(
            "src.skills.query_stats.handler.async_session",
            return_value=_mock_session(
                stats_rows=rows, total_val=Decimal("600"), income_val=None
            )(),
        ),
        patch(
            "src.skills.query_stats.handler.generate_text",
            new_callable=AsyncMock,
            return_value="Статистика: ...",
        ),
        patch(
            "src.skills.query_stats.handler.create_pie_chart",
            return_value="https://chart.url/pie.png",
        ) as mock_chart,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    mock_chart.assert_called_once()
    assert result.chart_url == "https://chart.url/pie.png"
