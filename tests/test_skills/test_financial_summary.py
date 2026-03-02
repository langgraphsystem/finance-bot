"""Tests for FinancialSummarySkill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.financial_summary.handler import FinancialSummarySkill, _resolve_period, skill


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="test-1",
        user_id="tg_123",
        chat_id="chat_123",
        type=MessageType.text,
        text=text,
    )


def _make_ctx(mock_sess):
    """Wrap a mock session in an async context manager."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_sess)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _session_factory(categories, merchants, income_val, prev_categories=None):
    """Build a side_effect callable for async_session.

    Call order in execute():
      1. _get_category_breakdown (current) → session.execute().all()
      2. _get_top_merchants → session.execute().all()
      3. _get_income_total → session.scalar()
      4. _get_category_breakdown (prev period) → session.execute().all()
    """
    sessions = []

    # 1. Category breakdown (current)
    s1 = AsyncMock()
    r1 = MagicMock()
    r1.all.return_value = categories
    s1.execute = AsyncMock(return_value=r1)
    sessions.append(_make_ctx(s1))

    # 2. Top merchants
    s2 = AsyncMock()
    r2 = MagicMock()
    r2.all.return_value = merchants
    s2.execute = AsyncMock(return_value=r2)
    sessions.append(_make_ctx(s2))

    # 3. Income total
    s3 = AsyncMock()
    s3.scalar = AsyncMock(return_value=income_val)
    sessions.append(_make_ctx(s3))

    # 4. Category breakdown (prev period)
    s4 = AsyncMock()
    r4 = MagicMock()
    r4.all.return_value = prev_categories or []
    s4.execute = AsyncMock(return_value=r4)
    sessions.append(_make_ctx(s4))

    call_idx = 0

    def factory():
        nonlocal call_idx
        idx = call_idx
        call_idx += 1
        return sessions[idx] if idx < len(sessions) else sessions[-1]

    return factory


def _make_cat_row(category, total, count):
    row = MagicMock()
    row.category = category
    row.total = total
    row.count = count
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_skill_attributes():
    """Skill has required attributes."""
    assert skill.name == "financial_summary"
    assert "financial_summary" in skill.intents
    assert isinstance(skill, FinancialSummarySkill)


async def test_no_family_id():
    """Returns setup message when no family_id."""
    from src.core.context import SessionContext

    ctx = SessionContext(
        user_id="u1", family_id=None, role="owner",
        language="en", currency="USD",
        business_type=None, categories=[], merchant_mappings=[],
    )
    message = _make_message("show me my summary")
    result = await skill.execute(message, ctx, {})
    assert "set up" in result.response_text.lower()


async def test_resolve_period_defaults_to_month():
    """Default period resolves to 'this month'."""
    _, _, label = _resolve_period({})
    assert label == "this month"


async def test_resolve_period_week():
    """Period 'week' resolves correctly."""
    _, _, label = _resolve_period({"period": "week"})
    assert label == "this week"


async def test_resolve_period_prev_month():
    """Period 'prev_month' resolves correctly."""
    _, _, label = _resolve_period({"period": "prev_month"})
    assert label == "last month"


async def test_resolve_period_year():
    """Period 'year' resolves correctly."""
    _, _, label = _resolve_period({"period": "year"})
    assert label == "this year"


async def test_no_data_returns_message(sample_context):
    """Empty DB returns no-data message."""
    message = _make_message("financial summary")
    intent_data = {"period": "month"}

    factory = _session_factory(
        categories=[], merchants=[], income_val=None,
    )
    with patch(
        "src.skills.financial_summary.handler.async_session",
        side_effect=factory,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    text_lower = result.response_text.lower()
    assert "no transactions" in text_lower or "транзакций не найдено" in text_lower


async def test_with_data_calls_llm(sample_context):
    """When DB has data, LLM is called to generate response."""
    message = _make_message("show me summary for this month")
    intent_data = {"period": "month"}

    cat_rows = [
        _make_cat_row("Food", 300.0, 15),
        _make_cat_row("Transport", 150.0, 8),
    ]

    factory = _session_factory(
        categories=cat_rows, merchants=[], income_val=1000.0,
    )
    with (
        patch(
            "src.skills.financial_summary.handler.async_session",
            side_effect=factory,
        ),
        patch(
            "src.skills.financial_summary.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Summary:</b> Food 300, Transport 150",
        ) as mock_llm,
        patch(
            "src.skills.financial_summary.handler.create_pie_chart",
            return_value="https://chart.url/pie.png",
        ),
    ):
        result = await skill.execute(message, sample_context, intent_data)

    mock_llm.assert_called_once()
    assert result.chart_url == "https://chart.url/pie.png"


async def test_chart_generated_with_categories(sample_context):
    """Pie chart is generated when 2+ categories present."""
    message = _make_message("expenses breakdown")
    intent_data = {"period": "month"}

    cat_rows = [
        _make_cat_row("Rent", 1000.0, 1),
        _make_cat_row("Food", 400.0, 20),
        _make_cat_row("Gas", 200.0, 10),
    ]

    factory = _session_factory(
        categories=cat_rows, merchants=[], income_val=0,
    )
    with (
        patch(
            "src.skills.financial_summary.handler.async_session",
            side_effect=factory,
        ),
        patch(
            "src.skills.financial_summary.handler.generate_text",
            new_callable=AsyncMock,
            return_value="Summary text",
        ),
        patch(
            "src.skills.financial_summary.handler.create_pie_chart",
            return_value="https://chart.url/pie.png",
        ) as mock_chart,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    mock_chart.assert_called_once()
    assert result.chart_url == "https://chart.url/pie.png"


async def test_format_data_includes_comparison():
    """_format_data includes comparison when previous period has data."""
    data_text = FinancialSummarySkill._format_data(
        categories=[{"category": "Food", "amount": 300.0, "count": 10}],
        merchants=[{"merchant": "Walmart", "amount": 200.0, "count": 5}],
        income=1000.0,
        expense_total=300.0,
        prev_total=250.0,
        period_label="this month",
        currency="USD",
    )
    assert "Compared to previous period" in data_text
    assert "up" in data_text
    assert "Food" in data_text
    assert "Walmart" in data_text
