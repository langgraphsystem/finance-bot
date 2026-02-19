"""Scheduled booking tasks — reminders, no-show detection, follow-ups."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, update

from src.core.db import async_session, rls_session
from src.core.models.booking import Booking
from src.core.models.enums import BookingStatus
from src.core.request_context import reset_family_context, set_family_context
from src.core.tasks.broker import broker

logger = logging.getLogger(__name__)


@broker.task(schedule=[{"cron": "* * * * *"}])  # Every minute
async def dispatch_booking_reminders():
    """Send reminders for bookings starting in 24h and 1h."""
    now = datetime.utcnow()
    windows = [
        ("24h", now + timedelta(hours=23, minutes=59), now + timedelta(hours=24, minutes=1)),
        ("1h", now + timedelta(minutes=59), now + timedelta(hours=1, minutes=1)),
    ]

    for label, window_start, window_end in windows:
        async with async_session() as session:
            result = await session.execute(
                select(Booking).where(
                    Booking.start_at >= window_start,
                    Booking.start_at <= window_end,
                    Booking.reminder_sent.is_(False),
                    Booking.status.in_(
                        [
                            BookingStatus.scheduled,
                            BookingStatus.confirmed,
                        ]
                    ),
                )
            )
            bookings = result.scalars().all()

        for booking in bookings:
            family_id = str(booking.family_id)
            token = set_family_context(family_id)
            try:
                async with rls_session(family_id) as session:
                    # Mark reminder as sent
                    await session.execute(
                        update(Booking).where(Booking.id == booking.id).values(reminder_sent=True)
                    )
                    await session.commit()

                logger.info(
                    "Booking reminder (%s) sent for '%s' at %s",
                    label,
                    booking.title,
                    booking.start_at,
                )
            except Exception as e:
                logger.error("Booking reminder failed for %s: %s", booking.id, e)
            finally:
                reset_family_context(token)


@broker.task(schedule=[{"cron": "*/15 * * * *"}])  # Every 15 minutes
async def detect_no_shows():
    """Mark bookings as no-show if 15+ minutes past start with no confirmation."""
    cutoff = datetime.utcnow() - timedelta(minutes=15)

    async with async_session() as session:
        result = await session.execute(
            select(Booking).where(
                Booking.start_at <= cutoff,
                Booking.status == BookingStatus.scheduled,
            )
        )
        overdue = result.scalars().all()

    for booking in overdue:
        family_id = str(booking.family_id)
        token = set_family_context(family_id)
        try:
            async with rls_session(family_id) as session:
                await session.execute(
                    update(Booking)
                    .where(Booking.id == booking.id)
                    .values(status=BookingStatus.no_show)
                )
                await session.commit()

            logger.info("Booking '%s' marked as no-show", booking.title)
        except Exception as e:
            logger.error("No-show detection failed for %s: %s", booking.id, e)
        finally:
            reset_family_context(token)
