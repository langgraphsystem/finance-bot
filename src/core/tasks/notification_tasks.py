"""Scheduled notification tasks (Taskiq cron)."""

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from src.core.config import settings
from src.core.db import async_session, rls_session
from src.core.locale_resolution import resolve_notification_locale
from src.core.models.enums import PaymentFrequency, Scope, TransactionType
from src.core.models.family import Family
from src.core.models.recurring_payment import RecurringPayment
from src.core.models.transaction import Transaction
from src.core.models.user import User
from src.core.models.user_profile import UserProfile
from src.core.notifications import collect_alerts, format_notification
from src.core.request_context import reset_family_context, set_family_context
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


@broker.task(schedule=[{"cron": "0 21 * * *"}])  # Daily at 21:00
async def daily_notifications():
    """Run daily anomaly and budget checks for all families."""
    async with async_session() as session:
        # Get all families
        result = await session.execute(select(Family))
        families = result.scalars().all()

    for family in families:
        family_id = str(family.id)
        token = set_family_context(family_id)
        try:
            # Resolve language for the family owner
            language = "en"
            async with rls_session(family_id) as session:
                user_result = await session.execute(
                    select(
                        User,
                        UserProfile.preferred_language,
                        UserProfile.notification_language,
                        UserProfile.timezone,
                        UserProfile.timezone_source,
                    )
                    .outerjoin(UserProfile, UserProfile.user_id == User.id)
                    .where(User.family_id == family.id)
                    .limit(1)
                )
                row = user_result.one_or_none()
                user = row[0] if row else None
                if user and row:
                    resolved = resolve_notification_locale(
                        user_language=user.language,
                        preferred_language=row[1],
                        notification_language=row[2],
                        timezone=row[3],
                        timezone_source=row[4],
                        use_v2_read=settings.ff_locale_v2_read,
                    )
                    language = resolved.language

            alerts = await collect_alerts(family_id, language=language)
            if alerts:
                await format_notification(alerts, language=language)

                if user:
                    logger.info(
                        "Notification for family %s (user %s): %d alerts language=%s",
                        family.id,
                        user.telegram_id,
                        len(alerts),
                        language,
                    )
        except Exception as e:
            logger.error("Notification failed for family %s: %s", family.id, e)
        finally:
            reset_family_context(token)


@broker.task(schedule=[{"cron": "0 10 * * 1"}])  # Weekly on Monday at 10:00
async def weekly_pattern_analysis():
    """Weekly pattern detection for all families."""
    from src.core.patterns import detect_patterns, store_patterns

    async with async_session() as session:
        result = await session.execute(select(Family))
        families = result.scalars().all()

    for family in families:
        family_id = str(family.id)
        token = set_family_context(family_id)
        try:
            patterns = await detect_patterns(family_id)
            if patterns:
                await store_patterns(family_id, patterns)
                logger.info(
                    "Pattern analysis complete for family %s: %d patterns",
                    family.id,
                    len(patterns.get("patterns", [])),
                )
        except Exception as e:
            logger.error("Pattern analysis failed for family %s: %s", family.id, e)
        finally:
            reset_family_context(token)


@broker.task(schedule=[{"cron": "0 8 * * *"}])  # Daily at 08:00
async def process_recurring_payments():
    """Auto-record recurring payments that are due today."""
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(RecurringPayment).where(
                RecurringPayment.is_active.is_(True),
                RecurringPayment.next_date <= today,
            )
        )
        payments = result.scalars().all()

    for payment in payments:
        family_id = str(payment.family_id)
        token = set_family_context(family_id)
        try:
            async with rls_session(family_id) as session:
                # Create transaction
                tx = Transaction(
                    family_id=payment.family_id,
                    user_id=payment.user_id,
                    category_id=payment.category_id,
                    type=TransactionType.expense,
                    amount=payment.amount,
                    description=f"Регулярный: {payment.name}",
                    date=today,
                    scope=Scope.family,
                    ai_confidence=Decimal("1.0"),
                    meta={"source": "recurring", "recurring_id": str(payment.id)},
                )
                session.add(tx)

                # Re-load payment inside this session to update next_date
                pay_result = await session.execute(
                    select(RecurringPayment).where(RecurringPayment.id == payment.id)
                )
                pay = pay_result.scalar_one()

                # Update next_date based on frequency
                if pay.frequency == PaymentFrequency.weekly:
                    pay.next_date = today + timedelta(weeks=1)
                elif pay.frequency == PaymentFrequency.monthly:
                    month = today.month + 1
                    year = today.year
                    if month > 12:
                        month = 1
                        year += 1
                    day = min(today.day, 28)  # Safe for all months
                    pay.next_date = date(year, month, day)
                elif pay.frequency == PaymentFrequency.quarterly:
                    month = today.month + 3
                    year = today.year
                    while month > 12:
                        month -= 12
                        year += 1
                    pay.next_date = date(year, month, min(today.day, 28))
                elif pay.frequency == PaymentFrequency.yearly:
                    pay.next_date = date(today.year + 1, today.month, today.day)

                await session.commit()
                logger.info("Recorded recurring payment: %s $%s", payment.name, payment.amount)
        except Exception as e:
            logger.error("Failed to process recurring payment %s: %s", payment.id, e)
        finally:
            reset_family_context(token)
