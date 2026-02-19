"""Tests for subscription management."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.billing.subscription import GRACE_PERIOD_DAYS, TRIAL_DAYS, is_active
from src.core.models.enums import SubscriptionStatus


@pytest.mark.asyncio
async def test_is_active_no_subscription():
    with patch("src.billing.subscription.get_subscription", new_callable=AsyncMock) as mock:
        mock.return_value = None
        assert not await is_active(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_is_active_active_subscription():
    sub = MagicMock()
    sub.status = SubscriptionStatus.active
    with patch("src.billing.subscription.get_subscription", new_callable=AsyncMock) as mock:
        mock.return_value = sub
        assert await is_active(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_is_active_trial_not_expired():
    sub = MagicMock()
    sub.status = SubscriptionStatus.trial
    sub.trial_ends_at = datetime.now(UTC) + timedelta(days=3)
    with patch("src.billing.subscription.get_subscription", new_callable=AsyncMock) as mock:
        mock.return_value = sub
        assert await is_active(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_is_active_trial_expired():
    sub = MagicMock()
    sub.status = SubscriptionStatus.trial
    sub.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    with patch("src.billing.subscription.get_subscription", new_callable=AsyncMock) as mock:
        mock.return_value = sub
        assert not await is_active(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_is_active_past_due_within_grace():
    sub = MagicMock()
    sub.status = SubscriptionStatus.past_due
    sub.current_period_end = datetime.now(UTC) - timedelta(days=1)
    with patch("src.billing.subscription.get_subscription", new_callable=AsyncMock) as mock:
        mock.return_value = sub
        # 1 day past due, grace is 3 days — should still be active
        assert await is_active(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_is_active_past_due_beyond_grace():
    sub = MagicMock()
    sub.status = SubscriptionStatus.past_due
    sub.current_period_end = datetime.now(UTC) - timedelta(days=10)
    with patch("src.billing.subscription.get_subscription", new_callable=AsyncMock) as mock:
        mock.return_value = sub
        assert not await is_active(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_is_active_cancelled():
    sub = MagicMock()
    sub.status = SubscriptionStatus.cancelled
    with patch("src.billing.subscription.get_subscription", new_callable=AsyncMock) as mock:
        mock.return_value = sub
        assert not await is_active(str(uuid.uuid4()))


def test_trial_days():
    assert TRIAL_DAYS == 7


def test_grace_period_days():
    assert GRACE_PERIOD_DAYS == 3
