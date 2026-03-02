"""Tests for TaxEstimateSkill."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.tax_estimate.handler import (
    TaxEstimateSkill,
    _current_quarter,
    _quarter_date_range,
    skill,
)


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        id="test-1",
        user_id="tg_123",
        chat_id="chat_123",
        type=MessageType.text,
        text=text,
    )


def _mock_session_for_tax(income_val=0, expense_val=0, categories=None):
    """Mock async_session for TaxEstimateSkill.

    _get_total is called multiple times (each opens its own session).
    """
    mock_sess = AsyncMock()
    # scalar is called once per _get_total invocation
    mock_sess.scalar = AsyncMock(side_effect=[income_val, expense_val])

    cat_result = MagicMock()
    cat_result.all.return_value = categories or []
    mock_sess.execute = AsyncMock(return_value=cat_result)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_sess)
    ctx.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=ctx)


def _make_cat_row(category, total):
    row = MagicMock()
    row.category = category
    row.total = total
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_skill_attributes():
    """Skill has required attributes."""
    assert skill.name == "tax_estimate"
    assert "tax_estimate" in skill.intents
    assert isinstance(skill, TaxEstimateSkill)


async def test_no_family_id():
    """Returns setup message when no family_id."""
    from src.core.context import SessionContext

    ctx = SessionContext(
        user_id="u1", family_id=None, role="owner",
        language="en", currency="USD",
        business_type=None, categories=[], merchant_mappings=[],
    )
    message = _make_message("estimate my taxes")
    result = await skill.execute(message, ctx, {})
    text_lower = result.response_text.lower()
    assert "set up" in text_lower or "настройте" in text_lower


async def test_current_quarter():
    """_current_quarter returns 1-4."""
    q = _current_quarter()
    assert 1 <= q <= 4


async def test_quarter_date_range():
    """_quarter_date_range returns correct date range."""
    start, end = _quarter_date_range(1, 2026)
    assert start.month == 1
    assert start.day == 1
    assert end.month == 4
    assert end.day == 1

    start4, end4 = _quarter_date_range(4, 2026)
    assert start4.month == 10
    assert end4.year == 2027
    assert end4.month == 1


async def test_no_data_returns_message(sample_context):
    """Returns no-data message when no transactions."""
    message = _make_message("tax estimate")
    intent_data = {}

    mock_factory = _mock_session_for_tax(income_val=None, expense_val=None)
    with patch(
        "src.skills.tax_estimate.handler.async_session",
        return_value=mock_factory(),
    ):
        result = await skill.execute(message, sample_context, intent_data)

    text_lower = result.response_text.lower()
    assert "no income" in text_lower or "нет данных" in text_lower


async def test_with_data_calls_llm(sample_context):
    """When data exists, LLM is called to generate response."""
    message = _make_message("how much tax do I owe?")
    intent_data = {}

    cat_rows = [_make_cat_row("Gas", 800.0), _make_cat_row("Insurance", 400.0)]

    mock_factory = _mock_session_for_tax(
        income_val=5000.0, expense_val=1200.0, categories=cat_rows,
    )
    with (
        patch(
            "src.skills.tax_estimate.handler.async_session",
            return_value=mock_factory(),
        ),
        patch(
            "src.skills.tax_estimate.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>Q1 Tax Estimate:</b> Income $5000, Expenses $1200",
        ) as mock_llm,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    mock_llm.assert_called_once()
    assert result.response_text is not None


async def test_estimate_income_tax_zero():
    """Zero or negative income returns zero tax."""
    assert TaxEstimateSkill._estimate_income_tax(0) == 0.0
    assert TaxEstimateSkill._estimate_income_tax(-1000) == 0.0


async def test_estimate_income_tax_first_bracket():
    """Income in first bracket taxed at 10%."""
    tax = TaxEstimateSkill._estimate_income_tax(10_000)
    assert tax == 10_000 * 0.10


async def test_estimate_income_tax_multiple_brackets():
    """Income spanning multiple brackets calculated correctly."""
    tax = TaxEstimateSkill._estimate_income_tax(50_000)
    # First 11,600 at 10% = 1,160
    # Next 35,550 at 12% = 4,266
    # Remaining 2,850 at 22% = 627
    expected = 11_600 * 0.10 + (47_150 - 11_600) * 0.12 + (50_000 - 47_150) * 0.22
    assert abs(tax - expected) < 0.01


async def test_self_employment_tax_for_business(sample_context):
    """Business users get self-employment tax in the estimate."""
    message = _make_message("quarterly taxes")
    intent_data = {}

    mock_factory = _mock_session_for_tax(income_val=10000.0, expense_val=2000.0)

    captured_args = {}

    async def capture_generate_text(**kwargs):
        captured_args.update(kwargs)
        return "<b>Tax estimate with SE tax</b>"

    with (
        patch(
            "src.skills.tax_estimate.handler.async_session",
            return_value=mock_factory(),
        ),
        patch(
            "src.skills.tax_estimate.handler.generate_text",
            side_effect=capture_generate_text,
        ),
    ):
        await skill.execute(message, sample_context, intent_data)

    # sample_context has business_type="trucker", so SE tax should appear
    assert "Self-employment tax" in captured_args.get("user_message", "")
