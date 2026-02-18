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

MODULE = "src.skills.undo_last.handler"


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

    with patch(
        f"{MODULE}.async_session",
        return_value=mock_session_ctx,
    ):
        result = await undo_skill.execute(sample_message, sample_ctx, {})

    assert "нет транзакций" in result.response_text.lower()


@pytest.mark.asyncio
async def test_returns_preview_with_buttons(undo_skill, sample_message, sample_ctx):
    """Returns preview + confirm/cancel buttons instead of deleting."""
    tx = _make_tx(sample_ctx.user_id, sample_ctx.family_id)

    mock_select_result = MagicMock()
    mock_select_result.scalar_one_or_none.return_value = tx

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_select_result

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()

    with (
        patch(
            f"{MODULE}.async_session",
            return_value=mock_session_ctx,
        ),
        patch("src.core.pending_actions.redis", mock_redis),
    ):
        result = await undo_skill.execute(sample_message, sample_ctx, {})

    assert "Удалить транзакцию" in result.response_text
    assert "42.50" in result.response_text or "42.5" in result.response_text
    assert result.buttons is not None
    assert len(result.buttons) == 2
    assert "confirm_action" in result.buttons[0]["callback"]
    assert "cancel_action" in result.buttons[1]["callback"]

    # Should NOT have deleted the transaction yet
    assert mock_session.execute.call_count == 1  # Only the SELECT


@pytest.mark.asyncio
async def test_execute_undo_deletes_and_logs():
    """execute_undo actually deletes the transaction and logs it."""
    from src.skills.undo_last.handler import execute_undo

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    action_data = {
        "tx_id": str(uuid.uuid4()),
        "tx_type": "expense",
        "tx_amount": "42.50",
        "tx_merchant": "Shell",
        "tx_description": "Diesel fuel",
    }

    with (
        patch(
            f"{MODULE}.async_session",
            return_value=mock_session_ctx,
        ),
        patch(
            f"{MODULE}.log_action",
            new_callable=AsyncMock,
        ) as mock_log,
    ):
        result = await execute_undo(action_data, "user-1", "family-1")

    assert "Отменено" in result
    assert "42.50" in result
    mock_session.execute.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
    mock_log.assert_awaited_once()
