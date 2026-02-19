"""Subscription management — CRUD, status checks, grace period logic."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.core.db import async_session
from src.core.models.enums import SubscriptionStatus
from src.core.models.subscription import Subscription

logger = logging.getLogger(__name__)

TRIAL_DAYS = 7
GRACE_PERIOD_DAYS = 3


async def get_subscription(family_id: str) -> Subscription | None:
    """Load the subscription for a family."""
    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.family_id == uuid.UUID(family_id))
        )
        return result.scalar_one_or_none()


async def ensure_subscription(family_id: str) -> Subscription:
    """Get or create a trial subscription for a family.

    Called on first message to guarantee every family has a subscription record.
    """
    sub = await get_subscription(family_id)
    if sub:
        return sub

    now = datetime.now(UTC)
    new_sub = Subscription(
        id=uuid.uuid4(),
        family_id=uuid.UUID(family_id),
        status=SubscriptionStatus.trial,
        plan="trial",
        trial_ends_at=now + timedelta(days=TRIAL_DAYS),
    )
    async with async_session() as session:
        session.add(new_sub)
        await session.commit()
        await session.refresh(new_sub)
    return new_sub


async def is_active(family_id: str) -> bool:
    """Check if the family has an active (or trial/grace) subscription."""
    sub = await get_subscription(family_id)
    if not sub:
        return False

    now = datetime.now(UTC)

    if sub.status == SubscriptionStatus.active:
        return True

    if sub.status == SubscriptionStatus.trial:
        return sub.trial_ends_at is not None and sub.trial_ends_at > now

    if sub.status == SubscriptionStatus.past_due:
        # Grace period: 3 days after current_period_end
        if sub.current_period_end:
            grace_end = sub.current_period_end + timedelta(days=GRACE_PERIOD_DAYS)
            return now < grace_end
        return False

    return False


async def update_from_stripe_event(event_type: str, data: dict) -> None:
    """Update subscription record from a Stripe webhook event.

    Handles: customer.subscription.created, .updated, .deleted,
    invoice.payment_failed.
    """
    stripe_sub = data.get("object", {})
    stripe_customer_id = stripe_sub.get("customer", "")
    stripe_sub_id = stripe_sub.get("id", "")

    if not stripe_customer_id:
        logger.warning("Stripe event missing customer ID: %s", event_type)
        return

    async with async_session() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.stripe_customer_id == stripe_customer_id)
        )
        sub = result.scalar_one_or_none()
        if not sub:
            logger.warning("No subscription found for Stripe customer %s", stripe_customer_id)
            return

        if event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
        ):
            status_map = {
                "active": SubscriptionStatus.active,
                "past_due": SubscriptionStatus.past_due,
                "canceled": SubscriptionStatus.cancelled,
                "trialing": SubscriptionStatus.trial,
            }
            stripe_status = stripe_sub.get("status", "")
            sub.status = status_map.get(stripe_status, SubscriptionStatus.active)
            sub.stripe_subscription_id = stripe_sub_id
            sub.plan = "pro"
            period_end = stripe_sub.get("current_period_end")
            if period_end:
                sub.current_period_end = datetime.fromtimestamp(period_end, tz=UTC)

        elif event_type == "customer.subscription.deleted":
            sub.status = SubscriptionStatus.cancelled

        elif event_type == "invoice.payment_failed":
            sub.status = SubscriptionStatus.past_due

        await session.commit()
        logger.info(
            "Subscription %s updated: status=%s (event=%s)",
            sub.id,
            sub.status.value,
            event_type,
        )
