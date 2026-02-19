"""Cancel booking skill — cancel an upcoming appointment."""

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
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

CANCEL_BOOKING_PROMPT = """\
You help users cancel bookings.
Identify which booking to cancel from the user's message.
Respond in the user's preferred language: {language}."""


class CancelBookingSkill:
    name = "cancel_booking"
    intents = ["cancel_booking"]
    model = "claude-haiku-4-5"

    @observe(name="cancel_booking")
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

        async with async_session() as session:
            query = (
                select(Booking)
                .where(
                    Booking.family_id == context.family_id,
                    Booking.start_at >= now,
                    Booking.status.in_([
                        BookingStatus.scheduled,
                        BookingStatus.confirmed,
                    ]),
                )
                .order_by(Booking.start_at)
            )

            if search:
                query = query.where(Booking.title.ilike(f"%{search}%"))

            result = await session.execute(query.limit(1))
            booking = result.scalar_one_or_none()

        if not booking:
            return SkillResult(response_text="No matching upcoming booking found to cancel.")

        async with async_session() as session:
            await session.execute(
                update(Booking)
                .where(Booking.id == booking.id)
                .values(status=BookingStatus.cancelled)
            )
            await session.commit()

        local_start = booking.start_at.astimezone(tz)
        return SkillResult(
            response_text=(
                f"Cancelled: <b>{booking.title}</b>\n"
                f"Was scheduled for {local_start.strftime('%b %d, %I:%M %p')}"
            )
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return CANCEL_BOOKING_PROMPT.format(language=context.language or "en")


skill = CancelBookingSkill()
