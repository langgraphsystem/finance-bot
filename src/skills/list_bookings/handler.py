"""List bookings skill — show today's/week's schedule."""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.booking import Booking
from src.core.models.enums import BookingStatus
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

LIST_BOOKINGS_PROMPT = """\
You help users view their booking schedule.
Show bookings in a clear, organized format.
Respond in the user's preferred language: {language}."""


class ListBookingsSkill:
    name = "list_bookings"
    intents = ["list_bookings"]
    model = "claude-haiku-4-5"

    @observe(name="list_bookings")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        tz = ZoneInfo(context.timezone)
        now = datetime.now(tz)
        period = intent_data.get("period") or "today"

        if period == "today":
            start_range = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_range = start_range + timedelta(days=1)
            label = "Today's"
        elif period == "week":
            start_range = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_range = start_range + timedelta(days=7)
            label = "This week's"
        else:
            start_range = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_range = start_range + timedelta(days=1)
            label = "Today's"

        async with async_session() as session:
            result = await session.execute(
                select(Booking)
                .where(
                    Booking.family_id == context.family_id,
                    Booking.start_at >= start_range,
                    Booking.start_at < end_range,
                    Booking.status.in_([
                        BookingStatus.scheduled,
                        BookingStatus.confirmed,
                    ]),
                )
                .order_by(Booking.start_at)
                .limit(50)
            )
            bookings = result.scalars().all()

        if not bookings:
            return SkillResult(
                response_text=f"{label} schedule is clear. No bookings."
            )

        lines = [f"<b>{label} bookings ({len(bookings)}):</b>\n"]
        for b in bookings:
            local_start = b.start_at.astimezone(tz)
            time_str = local_start.strftime("%I:%M %p")
            status_icon = "\u2705" if b.status == BookingStatus.confirmed else "\U0001f4c5"
            line = f"{status_icon} <b>{time_str}</b> — {b.title}"
            if b.location:
                line += f" @ {b.location}"
            lines.append(line)

        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        return LIST_BOOKINGS_PROMPT.format(language=context.language or "en")


skill = ListBookingsSkill()
