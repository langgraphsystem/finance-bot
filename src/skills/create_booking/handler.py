"""Create booking skill — schedule an appointment."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.db import async_session
from src.core.models.booking import Booking
from src.core.models.enums import BookingStatus
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

CREATE_BOOKING_PROMPT = """\
You help users create bookings and appointments.
Extract: title/service, date+time, duration, location, client name.
Current date/time in user's timezone ({timezone}): {now_local}.
Respond in the user's preferred language: {language}."""


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


class CreateBookingSkill:
    name = "create_booking"
    intents = ["create_booking"]
    model = "claude-haiku-4-5"

    @observe(name="create_booking")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        title = (
            intent_data.get("booking_title")
            or intent_data.get("event_title")
            or intent_data.get("description")
            or message.text
            or ""
        ).strip()

        if not title:
            return SkillResult(response_text="What should I book? Tell me the service and time.")

        tz = ZoneInfo(context.timezone)
        now = datetime.now(tz)

        start = _parse_datetime(
            intent_data.get("event_datetime") or intent_data.get("date"), tz
        )
        if not start:
            start = now + timedelta(hours=1)
            start = start.replace(minute=0, second=0, microsecond=0)

        duration_min = intent_data.get("event_duration_minutes") or 60
        end = start + timedelta(minutes=int(duration_min))

        location = intent_data.get("booking_location")
        service_type = intent_data.get("booking_service_type")
        contact_name = intent_data.get("contact_name")

        # Look up contact if name provided
        contact_id = None
        if contact_name:
            from sqlalchemy import select

            from src.core.models.contact import Contact

            async with async_session() as session:
                result = await session.execute(
                    select(Contact)
                    .where(
                        Contact.family_id == context.family_id,
                        Contact.name.ilike(f"%{contact_name}%"),
                    )
                    .limit(1)
                )
                contact = result.scalar_one_or_none()
                if contact:
                    contact_id = contact.id

        booking = Booking(
            id=uuid.uuid4(),
            family_id=uuid.UUID(context.family_id),
            user_id=uuid.UUID(context.user_id),
            contact_id=contact_id,
            title=title,
            service_type=service_type,
            start_at=start,
            end_at=end,
            location=location,
            status=BookingStatus.scheduled,
            source_channel=context.channel,
        )

        async with async_session() as session:
            session.add(booking)
            await session.commit()

        time_str = start.strftime("%b %d, %I:%M %p")
        parts = [f"Booked: <b>{title}</b>", f"When: {time_str}"]
        if contact_name:
            parts.append(f"Client: {contact_name}")
        if location:
            parts.append(f"Where: {location}")

        return SkillResult(response_text="\n".join(parts))

    def get_system_prompt(self, context: SessionContext) -> str:
        tz = ZoneInfo(context.timezone)
        now_local = datetime.now(tz)
        return CREATE_BOOKING_PROMPT.format(
            language=context.language or "en",
            timezone=context.timezone,
            now_local=now_local.strftime("%Y-%m-%d %H:%M"),
        )


skill = CreateBookingSkill()
