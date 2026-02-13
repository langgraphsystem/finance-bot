"""Tests for mark_paid skill."""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import LoadStatus, Scope
from src.gateway.types import IncomingMessage, MessageType
from src.skills.mark_paid.handler import MarkPaidSkill


@pytest.fixture
def mark_paid_skill():
    return MarkPaidSkill()


@pytest.fixture
def sample_message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="груз оплачен",
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


def _make_load(family_id: str, status: LoadStatus = LoadStatus.delivered) -> MagicMock:
    """Create a mock Load object."""
    load = MagicMock()
    load.id = uuid.uuid4()
    load.family_id = uuid.UUID(family_id)
    load.broker = "ABC Logistics"
    load.origin = "Chicago"
    load.destination = "Dallas"
    load.rate = Decimal("2500.00")
    load.ref_number = "REF-001"
    load.pickup_date = date(2026, 2, 10)
    load.delivery_date = date(2026, 2, 12)
    load.status = status
    load.paid_date = None
    return load


def _make_category(family_id: str) -> MagicMock:
    """Create a mock Category object."""
    cat = MagicMock()
    cat.id = uuid.uuid4()
    cat.family_id = uuid.UUID(family_id)
    cat.name = "Грузоперевозки"
    cat.scope = Scope.business
    return cat


def _create_mock_session(load, category=None):
    """Create a mock async session with configurable query results."""
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # First query: find delivered load
            result.scalar_one_or_none.return_value = load
        elif call_count == 2:
            if load is None:
                # Second query: fallback find pending/delivered load
                result.scalar_one_or_none.return_value = None
            else:
                # Second query: find business category
                result.scalar_one_or_none.return_value = category
        elif call_count == 3:
            # Third query: find business category (when first query returned None)
            result.scalar_one_or_none.return_value = category
        return result

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=mock_execute)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_session, mock_session_ctx


@pytest.mark.asyncio
async def test_no_loads_returns_message(mark_paid_skill, sample_message, sample_ctx):
    """When there are no unpaid loads, return informative message."""
    mock_session, mock_session_ctx = _create_mock_session(load=None)

    with patch("src.skills.mark_paid.handler.async_session", return_value=mock_session_ctx):
        result = await mark_paid_skill.execute(sample_message, sample_ctx, {})

    assert "неоплаченных" in result.response_text.lower() or "нет" in result.response_text.lower()


@pytest.mark.asyncio
async def test_delivered_load_marked_paid(mark_paid_skill, sample_message, sample_ctx):
    """When a delivered load exists, mark it as paid and create transaction."""
    load = _make_load(sample_ctx.family_id, LoadStatus.delivered)
    category = _make_category(sample_ctx.family_id)
    mock_session, mock_session_ctx = _create_mock_session(load=load, category=category)

    with (
        patch(
            "src.skills.mark_paid.handler.async_session",
            return_value=mock_session_ctx,
        ),
        patch(
            "src.skills.mark_paid.handler.log_action",
            new_callable=AsyncMock,
        ),
    ):
        result = await mark_paid_skill.execute(sample_message, sample_ctx, {})

    # Load status should be updated
    assert load.status == LoadStatus.paid
    assert load.paid_date == date.today()

    # Response should contain route and amount info
    assert "оплачен" in result.response_text.lower()
    assert "Chicago" in result.response_text
    assert "Dallas" in result.response_text
    assert "2500.00" in result.response_text

    # Transaction should be added to session
    mock_session.add.assert_called_once()
    tx = mock_session.add.call_args[0][0]
    assert tx.amount == load.rate
    assert tx.scope == Scope.business

    # Commit should be called
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_log_called_on_mark_paid(mark_paid_skill, sample_message, sample_ctx):
    """Verify that log_action is called with correct parameters."""
    load = _make_load(sample_ctx.family_id, LoadStatus.delivered)
    category = _make_category(sample_ctx.family_id)
    mock_session, mock_session_ctx = _create_mock_session(load=load, category=category)

    with (
        patch("src.skills.mark_paid.handler.async_session", return_value=mock_session_ctx),
        patch("src.skills.mark_paid.handler.log_action", new_callable=AsyncMock) as mock_log,
    ):
        await mark_paid_skill.execute(sample_message, sample_ctx, {})

    mock_log.assert_awaited_once()
    call_kwargs = mock_log.call_args.kwargs
    assert call_kwargs["session"] is mock_session
    assert call_kwargs["user_id"] == sample_ctx.user_id
    assert call_kwargs["family_id"] == sample_ctx.family_id
    assert call_kwargs["action"] == "mark_paid"
    assert call_kwargs["entity_type"] == "load"
    assert call_kwargs["entity_id"] == str(load.id)
    assert call_kwargs["old_data"]["status"] == "delivered"
    assert call_kwargs["new_data"]["status"] == "paid"
    assert "paid_date" in call_kwargs["new_data"]
