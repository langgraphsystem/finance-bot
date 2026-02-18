"""Find free slots skill — checks availability via Google Calendar API."""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)


class FindFreeSlotsSkill:
    name = "find_free_slots"
    intents = ["find_free_slots"]
    model = "claude-haiku-4-5"

    @observe(name="find_free_slots")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        prompt_result = await require_google_or_prompt(context.user_id)
        if prompt_result:
            return prompt_result

        google = await get_google_client(context.user_id)
        if not google:
            return SkillResult(response_text="Ошибка подключения к Calendar. Попробуйте /connect")

        # Use user's local timezone for business hours
        tz = ZoneInfo(context.timezone)
        now_local = datetime.now(tz)
        time_min = now_local.replace(hour=8, minute=0, second=0, microsecond=0)
        time_max = now_local.replace(hour=18, minute=0, second=0, microsecond=0)

        # If it's past 6 PM local time, check tomorrow
        if now_local.hour >= 18:
            time_min += timedelta(days=1)
            time_max += timedelta(days=1)

        try:
            busy_periods = await google.get_free_busy(time_min, time_max)
        except Exception as e:
            logger.warning("Calendar free/busy query failed: %s", e)
            return SkillResult(response_text="Ошибка при проверке расписания.")

        if not busy_periods:
            date_str = time_min.strftime("%d.%m.%Y")
            return SkillResult(
                response_text=(
                    f"📅 {date_str} — весь день свободен (8:00–18:00).\nЗапланировать что-нибудь?"
                )
            )

        # Compute free gaps
        free_slots = []
        current = time_min
        for period in busy_periods:
            busy_start = datetime.fromisoformat(period["start"]).astimezone(tz)
            busy_end = datetime.fromisoformat(period["end"]).astimezone(tz)
            if current < busy_start:
                free_slots.append(f"• {current.strftime('%H:%M')} — {busy_start.strftime('%H:%M')}")
            current = max(current, busy_end)
        if current < time_max:
            free_slots.append(f"• {current.strftime('%H:%M')} — {time_max.strftime('%H:%M')}")

        date_str = time_min.strftime("%d.%m.%Y")
        if free_slots:
            slots_text = "\n".join(free_slots)
            return SkillResult(
                response_text=(
                    f"<b>📅 Свободное время {date_str}:</b>\n{slots_text}\n\n"
                    f"Запланировать что-нибудь?"
                )
            )
        else:
            return SkillResult(
                response_text=f"📅 {date_str} — нет свободного времени с 8:00 до 18:00."
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return "Calendar assistant that finds free time slots."


skill = FindFreeSlotsSkill()
