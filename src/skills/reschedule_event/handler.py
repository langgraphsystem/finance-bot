"""Reschedule event skill — moves calendar events via Google Calendar API."""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

RESCHEDULE_SYSTEM_PROMPT = """\
Extract the reschedule request from the user's message.

Respond with ONLY a JSON object:
{{"event_id": "...", "event_name": "...", "new_date": "YYYY-MM-DD", "new_time": "HH:MM"}}

If info is missing, set the field to null.
Dates and times must be in the user's local timezone."""


class RescheduleEventSkill:
    name = "reschedule_event"
    intents = ["reschedule_event"]
    model = "gpt-5.2"

    @observe(name="reschedule_event")
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

        # Get upcoming events to find the one to reschedule
        tz = ZoneInfo(context.timezone)
        now_local = datetime.now(tz)
        try:
            events = await google.list_events(now_local, now_local + timedelta(days=7))
        except Exception as e:
            logger.warning("Calendar list failed: %s", e)
            return SkillResult(response_text="Ошибка при загрузке календаря.")

        if not events:
            return SkillResult(response_text="Нет предстоящих событий для переноса.")

        # Use LLM to match user request to an event
        import json

        events_list = "\n".join(
            f"{i}. {e.get('summary', '?')} — {e.get('start', {}).get('dateTime', '')}"
            f" (id: {e.get('id', '')})"
            for i, e in enumerate(events, 1)
        )

        details = await _parse_reschedule(message.text or "", events_list, context.language)
        try:
            parsed = json.loads(details)
        except (json.JSONDecodeError, TypeError):
            return SkillResult(
                response_text=(
                    "<b>Ваши ближайшие события:</b>\n"
                    + "\n".join(
                        f"• {e.get('summary', '?')} — {e.get('start', {}).get('dateTime', '')}"
                        for e in events[:5]
                    )
                    + "\n\nУкажите, какое событие перенести и на когда."
                )
            )

        event_id = parsed.get("event_id")
        event_name = parsed.get("event_name") or "событие"
        new_date = parsed.get("new_date")
        new_time = parsed.get("new_time")

        if not event_id or not new_date:
            return SkillResult(
                response_text=("Не удалось определить событие или новую дату. Уточните запрос.")
            )

        time_str = new_time or "09:00"

        # Store pending action — require user confirmation
        from src.core.pending_actions import store_pending_action

        pending_id = await store_pending_action(
            intent="reschedule_event",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "event_id": event_id,
                "event_name": event_name,
                "new_date": new_date,
                "new_time": time_str,
                "timezone": context.timezone,
            },
        )

        new_start = datetime.fromisoformat(f"{new_date}T{time_str}:00").replace(tzinfo=tz)
        preview = (
            f"<b>Перенести событие:</b>\n\n"
            f"📌 {event_name}\n"
            f"📅 Новая дата: {new_start.strftime('%d.%m.%Y %H:%M')}"
        )

        return SkillResult(
            response_text=preview,
            buttons=[
                {
                    "text": "🔄 Перенести",
                    "callback": f"confirm_action:{pending_id}",
                },
                {
                    "text": "❌ Отмена",
                    "callback": f"cancel_action:{pending_id}",
                },
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return RESCHEDULE_SYSTEM_PROMPT


async def _parse_reschedule(user_text: str, events_list: str, language: str) -> str:
    """Parse reschedule request via LLM, match to event."""
    system = (
        "Match the user's reschedule request to one of these events and extract new time.\n"
        'Respond with JSON: {"event_id": "...", "event_name": "...", '
        '"new_date": "YYYY-MM-DD", "new_time": "HH:MM"}\n'
        f"Events:\n{events_list}"
    )
    try:
        return await generate_text(
            "gpt-5.2", system, [{"role": "user", "content": user_text}], max_tokens=256
        )
    except Exception as e:
        logger.warning("Reschedule parse failed: %s", e)
        return "{}"


async def execute_reschedule(action_data: dict, user_id: str) -> str:
    """Actually reschedule the calendar event. Called after user confirms."""
    google = await get_google_client(user_id)
    if not google:
        return "Ошибка подключения к Calendar. Попробуйте /connect"

    event_id = action_data["event_id"]
    new_date = action_data["new_date"]
    new_time = action_data.get("new_time", "09:00")
    timezone = action_data.get("timezone", "America/New_York")
    tz = ZoneInfo(timezone)

    try:
        new_start = datetime.fromisoformat(f"{new_date}T{new_time}:00").replace(tzinfo=tz)
        new_end = new_start + timedelta(hours=1)

        await google.update_event(
            event_id,
            start={"dateTime": new_start.isoformat(), "timeZone": timezone},
            end={"dateTime": new_end.isoformat(), "timeZone": timezone},
        )
        return f"✅ Событие перенесено на {new_start.strftime('%d.%m.%Y %H:%M')}"
    except Exception as e:
        logger.error("Calendar update failed: %s", e)
        return "Ошибка при переносе события."


skill = RescheduleEventSkill()
