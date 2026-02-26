"""Tests for CashFlowForecastSkill."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.gateway.types import IncomingMessage, MessageType
from src.skills.cash_flow_forecast.handler import CashFlowForecastSkill, skill


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


async def test_skill_attributes():
    """Skill has required attributes."""
    assert skill.name == "cash_flow_forecast"
    assert "cash_flow_forecast" in skill.intents
    assert isinstance(skill, CashFlowForecastSkill)


async def test_no_family_id():
    """Returns setup message when no family_id."""
    from src.core.context import SessionContext

    ctx = SessionContext(
        user_id="u1", family_id=None, role="owner",
        language="en", currency="USD",
        business_type=None, categories=[], merchant_mappings=[],
    )
    message = _make_message("forecast my cash flow")
    result = await skill.execute(message, ctx, {})
    assert "set up" in result.response_text.lower()


async def test_insufficient_data(sample_context):
    """Returns message when less than 14 days of data."""
    message = _make_message("cash flow forecast")
    intent_data = {}

    # First transaction 5 days ago — not enough
    first_date = date.today() - timedelta(days=5)

    mock_sess = AsyncMock()
    mock_sess.scalar = AsyncMock(return_value=first_date)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_sess)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "src.skills.cash_flow_forecast.handler.async_session",
        return_value=ctx,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    assert "14 days" in result.response_text
    assert "5 days" in result.response_text


async def test_no_transactions_at_all(sample_context):
    """Returns message when no transactions at all."""
    message = _make_message("forecast")
    intent_data = {}

    mock_sess = AsyncMock()
    mock_sess.scalar = AsyncMock(return_value=None)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_sess)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "src.skills.cash_flow_forecast.handler.async_session",
        return_value=ctx,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    assert "14 days" in result.response_text
    assert "0 days" in result.response_text


async def test_parse_horizon_default():
    """Default horizon is 30 days."""
    horizon = CashFlowForecastSkill._parse_horizon({}, "forecast my cash flow")
    assert horizon == 30


async def test_parse_horizon_60():
    """Parses 60-day horizon."""
    assert CashFlowForecastSkill._parse_horizon({}, "forecast 60 days") == 60
    assert CashFlowForecastSkill._parse_horizon({}, "next 2 months") == 60


async def test_parse_horizon_90():
    """Parses 90-day horizon."""
    assert CashFlowForecastSkill._parse_horizon({}, "forecast 90 days") == 90
    assert CashFlowForecastSkill._parse_horizon({}, "next 3 months outlook") == 90


async def test_forecast_with_data_calls_llm(sample_context):
    """When sufficient data exists, LLM is called to generate forecast."""
    message = _make_message("forecast next month")
    intent_data = {}

    first_date = date.today() - timedelta(days=60)

    # We need multiple sessions: _get_first_transaction_date, _get_daily_averages (x2),
    # _get_weekly_pattern, _get_recurring_payments, _get_monthly_totals
    # Each opens its own async_session().

    call_count = 0

    def session_factory():
        nonlocal call_count
        call_count += 1

        mock_sess = AsyncMock()

        if call_count == 1:
            # _get_first_transaction_date → scalar
            mock_sess.scalar = AsyncMock(return_value=first_date)
        elif call_count in (2, 3):
            # _get_daily_averages (30d, 90d) → two scalars per call (income, expense)
            mock_sess.scalar = AsyncMock(side_effect=[500.0, 300.0])
        elif call_count == 4:
            # _get_weekly_pattern → execute().all()
            result = MagicMock()
            result.all.return_value = []
            mock_sess.execute = AsyncMock(return_value=result)
        elif call_count == 5:
            # _get_recurring_payments → scalars().all()
            scalars_result = MagicMock()
            scalars_result.all.return_value = []
            mock_sess.scalars = AsyncMock(return_value=scalars_result)
        else:
            # _get_monthly_totals → scalar for each month (income, expense x months)
            mock_sess.scalar = AsyncMock(return_value=0)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_sess)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    with (
        patch(
            "src.skills.cash_flow_forecast.handler.async_session",
            side_effect=session_factory,
        ),
        patch(
            "src.skills.cash_flow_forecast.handler.generate_text",
            new_callable=AsyncMock,
            return_value="<b>30-Day Forecast:</b> Net +$6,000",
        ) as mock_llm,
    ):
        result = await skill.execute(message, sample_context, intent_data)

    mock_llm.assert_called_once()
    assert result.response_text is not None
