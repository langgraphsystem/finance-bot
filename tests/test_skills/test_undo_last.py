"""Tests for undo_last skill."""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import SessionContext
from src.core.models.enums import Scope, TransactionType
from src.gateway.types import IncomingMessage, MessageType
from src.skills.undo_last.handler import UndoLastSkill


@pytest.fixture
def undo_skill():
    return UndoLastSkill()


@pytest.fixture
def sample_message():
    return IncomingMessage(
        id="msg-1",
        user_id="tg_user_1",
        chat_id="chat_1",
        type=MessageType.text,
        text="отмени последнюю",
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


def _make_tx(user_id: str, family_id: str) -> MagicMock:
    """Create a mock Transaction object."""
    tx = MagicMock()
    tx.id = uuid.uuid4()
    tx.user_id = uuid.UUID(user_id)
    tx.family_id = uuid.UUID(family_id)
    tx.type = TransactionType.expense
    tx.amount = Decimal("42.50")
    tx.merchant = "Shell"
    tx.description = "Diesel fuel"
    tx.date = date.today()
    tx.scope = Scope.business
    tx.created_at = MagicMock()
    return tx


@pytest.mark.asyncio
async def test_no_transactions_returns_message(undo_skill, sample_message, sample_ctx):
    """When user has no transactions, return informative message."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.skills.undo_last.handler.async_session", return_value=mock_session_ctx):
        result = await undo_skill.execute(sample_message, sample_ctx, {})

    assert "нет транзакций" in result.response_text.lower()


@pytest.mark.asyncio
async def test_deletes_last_transaction(undo_skill, sample_message, sample_ctx):
    """When user has a transaction, delete it and return confirmation."""
    tx = _make_tx(sample_ctx.user_id, sample_ctx.family_id)

    mock_select_result = MagicMock()
    mock_select_result.scalar_one_or_none.return_value = tx

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_select_result
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "src.skills.undo_last.handler.async_session",
            return_value=mock_session_ctx,
        ),
        patch(
            "src.skills.undo_last.handler.log_action",
            new_callable=AsyncMock,
        ),
    ):
        result = await undo_skill.execute(sample_message, sample_ctx, {})

    assert "Отменено" in result.response_text
    assert "42.50" in result.response_text or "42.5" in result.response_text
    assert "Shell" in result.response_text

    # Verify delete was called (second execute call after the select)
    assert mock_session.execute.call_count == 2

    # Verify commit was called
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_log_called_on_undo(undo_skill, sample_message, sample_ctx):
    """Verify that log_action is called with correct parameters on undo."""
    tx = _make_tx(sample_ctx.user_id, sample_ctx.family_id)

    mock_select_result = MagicMock()
    mock_select_result.scalar_one_or_none.return_value = tx

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_select_result
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.skills.undo_last.handler.async_session", return_value=mock_session_ctx),
        patch("src.skills.undo_last.handler.log_action", new_callable=AsyncMock) as mock_log,
    ):
        await undo_skill.execute(sample_message, sample_ctx, {})

    mock_log.assert_awaited_once()
    call_kwargs = mock_log.call_args.kwargs
    assert call_kwargs["session"] is mock_session
    assert call_kwargs["user_id"] == sample_ctx.user_id
    assert call_kwargs["family_id"] == sample_ctx.family_id
    assert call_kwargs["action"] == "undo_last"
    assert call_kwargs["entity_type"] == "transaction"
    assert call_kwargs["entity_id"] == str(tx.id)
    assert call_kwargs["old_data"]["type"] == "expense"
    assert call_kwargs["old_data"]["amount"] == str(tx.amount)
    assert call_kwargs["old_data"]["merchant"] == "Shell"
    assert call_kwargs["new_data"] is None
