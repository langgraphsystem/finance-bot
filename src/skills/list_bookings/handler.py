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
from src.skills._i18n import fmt_time, register_strings, t
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "today": "Today's",
        "week": "This week's",
        "empty": "📋 {label} schedule is clear. No bookings.",
        "header": "📋 <b>{label} bookings ({count}):</b>\n",
        "action": "\nBook another? Just tell me.",
    },
    "ru": {
        "today": "Сегодня",
        "week": "На этой неделе",
        "empty": "📋 {label} — расписание свободно.",
        "header": "📋 <b>{label} — записи ({count}):</b>\n",
        "action": "\nЗабронировать ещё? Просто скажи.",
    },
    "es": {
        "today": "Hoy",
        "week": "Esta semana",
        "empty": "📋 {label} — sin reservas.",
        "header": "📋 <b>{label} — reservas ({count}):</b>\n",
        "action": "\n¿Reservar otra? Solo dime.",
    },
}
register_strings("list_bookings", _STRINGS)

LIST_BOOKINGS_PROMPT = """\
You help users view their booking schedule.
Show bookings in a clear, organized format.
ALWAYS respond in the same language as the user's message/query."""


class ListBookingsSkill:
    name = "list_bookings"
    intents = ["list_bookings"]
    model = "gpt-5.4-2026-03-05"

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
        lang = context.language or "en"

        if period == "today":
            start_range = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_range = start_range + timedelta(days=1)
            label = t(_STRINGS, "today", lang)
        elif period == "week":
            start_range = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_range = start_range + timedelta(days=7)
            label = t(_STRINGS, "week", lang)
        else:
            start_range = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_range = start_range + timedelta(days=1)
            label = t(_STRINGS, "today", lang)

        async with async_session() as session:
            result = await session.execute(
                select(Booking)
                .where(
                    Booking.family_id == context.family_id,
                    Booking.start_at >= start_range,
                    Booking.start_at < end_range,
                    Booking.status.in_(
                        [
                            BookingStatus.scheduled,
                            BookingStatus.confirmed,
                        ]
                    ),
                )
                .order_by(Booking.start_at)
                .limit(50)
            )
            bookings = result.scalars().all()

        if not bookings:
            return SkillResult(response_text=t(_STRINGS, "empty", lang, label=label))

        lines = [t(_STRINGS, "header", lang, label=label, count=str(len(bookings)))]
        for b in bookings:
            local_start = b.start_at.astimezone(tz)
            time_str = fmt_time(local_start, lang)
            status_icon = "\u2705" if b.status == BookingStatus.confirmed else "\U0001f4c5"
            line = f"{status_icon} <b>{time_str}</b> — {b.title}"
            if b.location:
                line += f" @ {b.location}"
            lines.append(line)

        lines.append(t(_STRINGS, "action", lang))
        return SkillResult(response_text="\n".join(lines))

    def get_system_prompt(self, context: SessionContext) -> str:
        return LIST_BOOKINGS_PROMPT.format(language=context.language or "en")


skill = ListBookingsSkill()
