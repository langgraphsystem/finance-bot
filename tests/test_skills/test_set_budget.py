"""Tests for set_budget skill."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import BudgetPeriod
from src.gateway.types import IncomingMessage, MessageType
from src.skills.set_budget.handler import SetBudgetSkill


@pytest.fixture
def budget_skill():
    return SetBudgetSkill()


@pytest.fixture
def sample_message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="бюджет на продукты 30000",
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
        categories=[
            {"id": str(uuid.uuid4()), "name": "Продукты", "scope": "family", "icon": "🛒"},
            {"id": str(uuid.uuid4()), "name": "Дизель", "scope": "business", "icon": "⛽"},
        ],
        merchant_mappings=[],
    )


def _mock_session_context(mock_session):
    """Create an async context manager wrapping mock_session."""
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


@pytest.mark.asyncio
async def test_budget_created_successfully(budget_skill, sample_message, sample_ctx):
    """Budget is created when none exists for the category."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    intent_data = {
        "amount": 30000,
        "category": "Продукты",
        "period": "monthly",
    }

    with patch(
        "src.skills.set_budget.handler.async_session",
        return_value=_mock_session_context(mock_session),
    ):
        result = await budget_skill.execute(sample_message, sample_ctx, intent_data)

    assert "установлен" in result.response_text
    assert "Продукты" in result.response_text
    assert "30000" in result.response_text
    assert "в месяц" in result.response_text
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_budget_updated_when_exists(budget_skill, sample_message, sample_ctx):
    """Existing budget is updated with new amount and period."""
    existing_budget = MagicMock()
    existing_budget.amount = Decimal("20000")
    existing_budget.period = BudgetPeriod.monthly

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_budget

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_session.commit = AsyncMock()

    intent_data = {
        "amount": 35000,
        "category": "Продукты",
        "period": "weekly",
    }

    with patch(
        "src.skills.set_budget.handler.async_session",
        return_value=_mock_session_context(mock_session),
    ):
        result = await budget_skill.execute(sample_message, sample_ctx, intent_data)

    assert "обновлён" in result.response_text
    assert "Продукты" in result.response_text
    assert "35000" in result.response_text
    assert "в неделю" in result.response_text
    assert existing_budget.amount == Decimal("35000")
    assert existing_budget.period == BudgetPeriod.weekly
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_amount_returns_error(budget_skill, sample_message, sample_ctx):
    """When amount is missing, return an error message."""
    intent_data = {
        "category": "Продукты",
    }

    result = await budget_skill.execute(sample_message, sample_ctx, intent_data)

    assert "Укажите сумму" in result.response_text


@pytest.mark.asyncio
async def test_category_not_found_creates_general_budget(budget_skill, sample_message, sample_ctx):
    """When category is not found in context, create a general budget."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    intent_data = {
        "amount": 50000,
        "category": "Несуществующая",
        "period": "monthly",
    }

    with patch(
        "src.skills.set_budget.handler.async_session",
        return_value=_mock_session_context(mock_session),
    ):
        result = await budget_skill.execute(sample_message, sample_ctx, intent_data)

    assert "установлен" in result.response_text
    assert "общий" in result.response_text
    assert "50000" in result.response_text
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()
