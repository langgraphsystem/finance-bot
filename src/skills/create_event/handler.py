"""Create event skill — creates real calendar events via Google Calendar API."""

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

CREATE_EVENT_SYSTEM_PROMPT = """\
You are a calendar assistant. Extract event details from the user's message.

Current date/time in user's timezone ({timezone}): {now_local}

Respond with ONLY a JSON object (no markdown, no explanation):
{{"title": "...", "date": "YYYY-MM-DD", "time": "HH:MM", "duration_hours": 1, "location": null}}

If info is missing, use reasonable defaults:
- date: today ({today_date})
- time: next round hour
- duration: 1 hour
- location: null

IMPORTANT: "date" and "time" must be in the USER'S LOCAL timezone ({timezone}), NOT UTC.
"tomorrow" means {tomorrow_date}.

Respond in: {language}."""


class CreateEventSkill:
    name = "create_event"
    intents = ["create_event"]
    model = "gpt-5.2"

    @observe(name="create_event")
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

        event_title = intent_data.get("event_title") or ""
        event_datetime = intent_data.get("event_datetime") or ""
        query = message.text or ""
        tz = ZoneInfo(context.timezone)

        # Use LLM to extract structured event details
        import json

        details = await _extract_event_details(
            event_title, event_datetime, query, context.language, context.timezone
        )
        try:
            parsed = json.loads(details)
        except (json.JSONDecodeError, TypeError):
            parsed = {"title": event_title or query, "date": None, "time": None}

        title = parsed.get("title") or event_title or "Новое событие"
        now_local = datetime.now(tz)

        try:
            date_str = parsed.get("date") or now_local.strftime("%Y-%m-%d")
            time_str = parsed.get("time") or (now_local + timedelta(hours=1)).strftime("%H:%M")
            start = datetime.fromisoformat(f"{date_str}T{time_str}:00").replace(tzinfo=tz)
        except (ValueError, TypeError):
            start = now_local + timedelta(hours=1)

        duration = float(parsed.get("duration_hours", 1) or 1)
        end = start + timedelta(hours=duration)
        location = parsed.get("location")

        # Store pending action — require user confirmation
        from src.core.pending_actions import store_pending_action

        pending_id = await store_pending_action(
            intent="create_event",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "title": title,
                "start_iso": start.isoformat(),
                "end_iso": end.isoformat(),
                "location": location,
                "timezone": context.timezone,
            },
        )

        preview = (
            f"<b>Новое событие:</b>\n\n"
            f"📌 <b>{title}</b>\n"
            f"📅 {start.strftime('%d.%m.%Y %H:%M')} — "
            f"{end.strftime('%H:%M')}\n"
            f"{f'📍 {location}' if location else ''}"
        )

        return SkillResult(
            response_text=preview,
            buttons=[
                {
                    "text": "✅ Создать",
                    "callback": f"confirm_action:{pending_id}",
                },
                {
                    "text": "❌ Отмена",
                    "callback": f"cancel_action:{pending_id}",
                },
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        tz = ZoneInfo(context.timezone)
        now_local = datetime.now(tz)
        return CREATE_EVENT_SYSTEM_PROMPT.format(
            language=context.language or "ru",
            timezone=context.timezone,
            now_local=now_local.strftime("%Y-%m-%d %H:%M"),
            today_date=now_local.strftime("%Y-%m-%d"),
            tomorrow_date=(now_local + timedelta(days=1)).strftime("%Y-%m-%d"),
        )


async def _extract_event_details(
    title: str, dt: str, user_text: str, language: str, timezone: str
) -> str:
    """Extract event details as JSON via LLM."""
    tz = ZoneInfo(timezone)
    now_local = datetime.now(tz)
    system = CREATE_EVENT_SYSTEM_PROMPT.format(
        language=language or "ru",
        timezone=timezone,
        now_local=now_local.strftime("%Y-%m-%d %H:%M"),
        today_date=now_local.strftime("%Y-%m-%d"),
        tomorrow_date=(now_local + timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    prompt = f"Title hint: {title}\nDatetime hint: {dt}\nUser said: {user_text}"
    try:
        return await generate_text(
            "gpt-5.2", system, [{"role": "user", "content": prompt}], max_tokens=256
        )
    except Exception as e:
        logger.warning("Create event LLM failed: %s", e)
        return "{}"


async def execute_create_event(action_data: dict, user_id: str) -> str:
    """Actually create the calendar event. Called after user confirms."""
    google = await get_google_client(user_id)
    if not google:
        return "Ошибка подключения к Calendar. Попробуйте /connect"

    title = action_data["title"]
    start = datetime.fromisoformat(action_data["start_iso"])
    end = datetime.fromisoformat(action_data["end_iso"])
    location = action_data.get("location")
    timezone = action_data.get("timezone", "America/New_York")

    try:
        event = await google.create_event(
            title=title, start=start, end=end, location=location, timezone=timezone
        )
        event_link = event.get("htmlLink", "")
        location_line = f"📍 {location}" if location else ""
        link_line = f"\n🔗 {event_link}" if event_link else ""
        return (
            f"✅ Создано: <b>{title}</b>\n"
            f"📅 {start.strftime('%d.%m.%Y %H:%M')} — "
            f"{end.strftime('%H:%M')}\n"
            f"{location_line}"
            f"{link_line}"
        )
    except Exception as e:
        logger.error("Calendar create_event failed: %s", e)
        return f"Ошибка при создании события «{title}». Попробуйте позже."


skill = CreateEventSkill()
