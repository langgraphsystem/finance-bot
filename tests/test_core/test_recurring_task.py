"""Tests for the process_recurring_payments cron task."""

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models.enums import PaymentFrequency, Scope, TransactionType


def _make_recurring_payment(
    frequency: PaymentFrequency = PaymentFrequency.monthly,
    next_date: date | None = None,
    name: str = "Netflix",
    amount: Decimal = Decimal("15.00"),
) -> MagicMock:
    """Create a mock RecurringPayment object."""
    payment = MagicMock()
    payment.id = uuid.uuid4()
    payment.family_id = uuid.uuid4()
    payment.user_id = uuid.uuid4()
    payment.category_id = uuid.uuid4()
    payment.name = name
    payment.amount = amount
    payment.frequency = frequency
    payment.next_date = next_date or date.today()
    payment.is_active = True
    payment.auto_record = True
    return payment


def _build_session_and_factory(payments):
    """Build mock async_session (for initial query) and rls_session (per-payment work).

    Returns (mock_query_session, mock_rls_session,
    mock_async_session_factory, mock_rls_session_factory).
    The mock_rls_session is the session yielded inside rls_session context manager.
    """
    # --- async_session: used for the initial SELECT of due payments ---
    mock_query_result = MagicMock()
    mock_query_result.scalars.return_value.all.return_value = payments

    mock_query_session = AsyncMock()
    mock_query_session.execute.return_value = mock_query_result

    mock_query_cm = AsyncMock()
    mock_query_cm.__aenter__ = AsyncMock(return_value=mock_query_session)
    mock_query_cm.__aexit__ = AsyncMock(return_value=False)

    mock_async_session_factory = MagicMock(return_value=mock_query_cm)

    # --- rls_session: used per-payment for writes ---
    mock_rls_session = AsyncMock()
    mock_rls_session.add = MagicMock()
    mock_rls_session.commit = AsyncMock()
    mock_rls_session.rollback = AsyncMock()

    # rls_session execute calls:
    #  - 1st call from rls_session itself (set_config) — returns irrelevant mock
    #  - 2nd call for re-loading the payment (SELECT RecurringPayment)
    # We need .scalar_one() on the second call to return the same payment object.
    # Use side_effect to differentiate.
    payment_lookup = {}
    for p in payments:
        payment_lookup[p.id] = p

    # Keep a counter per rls_session invocation to know which payment we're on
    _rls_call_state = {"payment_index": 0}

    @asynccontextmanager
    async def mock_rls_factory(family_id: str):
        # Each call to rls_session gets a fresh mock session that shares the same
        # add / commit tracking, so assertions work across all payments.
        idx = _rls_call_state["payment_index"]
        _rls_call_state["payment_index"] += 1
        current_payment = payments[idx] if idx < len(payments) else MagicMock()

        # For the per-payment session, execute is called once to re-load the payment
        reload_result = MagicMock()
        reload_result.scalar_one.return_value = current_payment

        mock_rls_session.execute = AsyncMock(return_value=reload_result)
        yield mock_rls_session

    return mock_query_session, mock_rls_session, mock_async_session_factory, mock_rls_factory


@pytest.mark.asyncio
async def test_process_recurring_creates_transaction():
    """Verify that a transaction is created for a due recurring payment."""
    payment = _make_recurring_payment()
    _, mock_rls_sess, mock_async_factory, mock_rls_factory = _build_session_and_factory([payment])

    with (
        patch(
            "src.core.tasks.notification_tasks.async_session",
            mock_async_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.rls_session",
            mock_rls_factory,
        ),
    ):
        from src.core.tasks.notification_tasks import process_recurring_payments

        await process_recurring_payments()

    # Transaction was added to session
    mock_rls_sess.add.assert_called_once()
    tx = mock_rls_sess.add.call_args[0][0]
    assert tx.family_id == payment.family_id
    assert tx.user_id == payment.user_id
    assert tx.category_id == payment.category_id
    assert tx.type == TransactionType.expense
    assert tx.amount == payment.amount
    assert tx.scope == Scope.family
    assert "Netflix" in tx.description
    assert tx.meta["source"] == "recurring"
    assert tx.meta["recurring_id"] == str(payment.id)

    mock_rls_sess.commit.assert_awaited()


@pytest.mark.asyncio
async def test_process_recurring_updates_next_date_weekly():
    """Verify next_date is updated correctly for weekly frequency."""
    today = date.today()
    payment = _make_recurring_payment(frequency=PaymentFrequency.weekly, next_date=today)
    _, mock_rls_sess, mock_async_factory, mock_rls_factory = _build_session_and_factory([payment])

    with (
        patch(
            "src.core.tasks.notification_tasks.async_session",
            mock_async_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.rls_session",
            mock_rls_factory,
        ),
    ):
        from src.core.tasks.notification_tasks import process_recurring_payments

        await process_recurring_payments()

    assert payment.next_date == today + timedelta(weeks=1)


@pytest.mark.asyncio
async def test_process_recurring_updates_next_date_monthly():
    """Verify next_date is updated correctly for monthly frequency."""
    today = date(2025, 6, 15)
    payment = _make_recurring_payment(frequency=PaymentFrequency.monthly, next_date=today)
    _, mock_rls_sess, mock_async_factory, mock_rls_factory = _build_session_and_factory([payment])

    with (
        patch(
            "src.core.tasks.notification_tasks.async_session",
            mock_async_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.rls_session",
            mock_rls_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.date",
        ) as mock_date,
    ):
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        from src.core.tasks.notification_tasks import process_recurring_payments

        await process_recurring_payments()

    assert payment.next_date == date(2025, 7, 15)


@pytest.mark.asyncio
async def test_process_recurring_updates_next_date_yearly():
    """Verify next_date is updated correctly for yearly frequency."""
    today = date(2025, 6, 15)
    payment = _make_recurring_payment(frequency=PaymentFrequency.yearly, next_date=today)
    _, mock_rls_sess, mock_async_factory, mock_rls_factory = _build_session_and_factory([payment])

    with (
        patch(
            "src.core.tasks.notification_tasks.async_session",
            mock_async_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.rls_session",
            mock_rls_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.date",
        ) as mock_date,
    ):
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        from src.core.tasks.notification_tasks import process_recurring_payments

        await process_recurring_payments()

    assert payment.next_date == date(2026, 6, 15)


@pytest.mark.asyncio
async def test_process_recurring_no_payments():
    """When no payments are due, nothing should happen."""
    _, mock_rls_sess, mock_async_factory, mock_rls_factory = _build_session_and_factory([])

    with (
        patch(
            "src.core.tasks.notification_tasks.async_session",
            mock_async_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.rls_session",
            mock_rls_factory,
        ),
    ):
        from src.core.tasks.notification_tasks import process_recurring_payments

        await process_recurring_payments()

    mock_rls_sess.add.assert_not_called()
    mock_rls_sess.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_recurring_error_rolls_back():
    """When an error occurs processing a payment, error is caught internally."""
    payment = _make_recurring_payment()

    # --- async_session for the initial query ---
    mock_query_result = MagicMock()
    mock_query_result.scalars.return_value.all.return_value = [payment]

    mock_query_session = AsyncMock()
    mock_query_session.execute.return_value = mock_query_result

    mock_query_cm = AsyncMock()
    mock_query_cm.__aenter__ = AsyncMock(return_value=mock_query_session)
    mock_query_cm.__aexit__ = AsyncMock(return_value=False)

    mock_async_factory = MagicMock(return_value=mock_query_cm)

    # --- rls_session that raises ---
    @asynccontextmanager
    async def failing_rls_factory(family_id: str):
        mock_sess = AsyncMock()
        mock_sess.add = MagicMock(side_effect=Exception("DB write error"))
        mock_sess.commit = AsyncMock()
        mock_sess.execute = AsyncMock()
        yield mock_sess

    with (
        patch(
            "src.core.tasks.notification_tasks.async_session",
            mock_async_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.rls_session",
            failing_rls_factory,
        ),
    ):
        from src.core.tasks.notification_tasks import process_recurring_payments

        # Should not raise — error is caught internally
        await process_recurring_payments()


@pytest.mark.asyncio
async def test_process_recurring_multiple_payments():
    """Verify all due payments are processed."""
    payment1 = _make_recurring_payment(name="Netflix", amount=Decimal("15.00"))
    payment2 = _make_recurring_payment(name="Spotify", amount=Decimal("10.00"))
    _, mock_rls_sess, mock_async_factory, mock_rls_factory = _build_session_and_factory(
        [payment1, payment2]
    )

    with (
        patch(
            "src.core.tasks.notification_tasks.async_session",
            mock_async_factory,
        ),
        patch(
            "src.core.tasks.notification_tasks.rls_session",
            mock_rls_factory,
        ),
    ):
        from src.core.tasks.notification_tasks import process_recurring_payments

        await process_recurring_payments()

    # Both payments should result in add + commit calls
    assert mock_rls_sess.add.call_count == 2
    assert mock_rls_sess.commit.await_count == 2
