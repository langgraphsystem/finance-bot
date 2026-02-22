"""Reschedule booking skill — move an appointment to a new time."""

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.booking import Booking
from src.core.models.enums import BookingStatus
from src.core.observability import observe
from src.core.search_utils import ilike_all_words, split_search_words
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

RESCHEDULE_BOOKING_PROMPT = """\
You help users reschedule bookings to a new date/time.
Extract: which booking, new date/time.
Current date/time ({timezone}): {now_local}.
ALWAYS respond in the same language as the user's message/query."""


def _parse_datetime(raw: str | None, tz: ZoneInfo) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt
    except (ValueError, TypeError):
        return None


class RescheduleBookingSkill:
    name = "reschedule_booking"
    intents = ["reschedule_booking"]
    model = "gpt-5.2"

    @observe(name="reschedule_booking")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        search = (
            intent_data.get("booking_title")
            or intent_data.get("contact_name")
            or intent_data.get("description")
            or ""
        ).strip()

        tz = ZoneInfo(context.timezone)
        now = datetime.now(tz)

        new_start = _parse_datetime(
            intent_data.get("event_datetime") or intent_data.get("date"), tz
        )

        if not new_start:
            return SkillResult(
                response_text="When should I reschedule it to? Give me a date and time."
            )

        async with async_session() as session:
            query = (
                select(Booking)
                .where(
                    Booking.family_id == context.family_id,
                    Booking.start_at >= now,
                    Booking.status.in_(
                        [
                            BookingStatus.scheduled,
                            BookingStatus.confirmed,
                        ]
                    ),
                )
                .order_by(Booking.start_at)
            )
            if search:
                words = split_search_words(search)
                if words:
                    query = query.where(ilike_all_words(Booking.title, words))
                else:
                    query = query.where(Booking.title.ilike(f"%{search}%"))

            result = await session.execute(query.limit(1))
            booking = result.scalar_one_or_none()

        if not booking:
            return SkillResult(response_text="No matching upcoming booking found to reschedule.")

        duration = booking.end_at - booking.start_at
        new_end = new_start + duration

        async with async_session() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == booking.id)
                .values(
                    start_at=new_start,
                    end_at=new_end,
                    status=BookingStatus.scheduled,
                    reminder_sent=False,
                    confirmation_sent=False,
                )
            )
            await session.commit()

        return SkillResult(
            response_text=(
                f"Rescheduled: <b>{booking.title}</b>\n"
                f"New time: {new_start.strftime('%b %d, %I:%M %p')}"
            )
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        tz = ZoneInfo(context.timezone)
        now_local = datetime.now(tz)
        return RESCHEDULE_BOOKING_PROMPT.format(
            language=context.language or "en",
            timezone=context.timezone,
            now_local=now_local.strftime("%Y-%m-%d %H:%M"),
        )


skill = RescheduleBookingSkill()
