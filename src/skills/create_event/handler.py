"""Create event skill — creates real calendar events via Google Calendar API."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

CREATE_EVENT_SYSTEM_PROMPT = """\
You are a calendar assistant. Extract event details from the user's message.

Respond with ONLY a JSON object (no markdown, no explanation):
{{"title": "...", "date": "YYYY-MM-DD", "time": "HH:MM", "duration_hours": 1, "location": null}}

If info is missing, use reasonable defaults:
- date: today
- time: next round hour
- duration: 1 hour
- location: null

Respond in: {language}."""


class CreateEventSkill:
    name = "create_event"
    intents = ["create_event"]
    model = "claude-haiku-4-5"

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

        # Use LLM to extract structured event details
        import json

        details = await _extract_event_details(
            event_title, event_datetime, query, context.language
        )
        try:
            parsed = json.loads(details)
        except (json.JSONDecodeError, TypeError):
            parsed = {"title": event_title or query, "date": None, "time": None}

        title = parsed.get("title") or event_title or "Новое событие"
        now = datetime.now(UTC)

        try:
            date_str = parsed.get("date") or now.strftime("%Y-%m-%d")
            time_str = parsed.get("time") or (now + timedelta(hours=1)).strftime("%H:%M")
            start = datetime.fromisoformat(f"{date_str}T{time_str}:00+00:00")
        except (ValueError, TypeError):
            start = now + timedelta(hours=1)

        duration = float(parsed.get("duration_hours", 1) or 1)
        end = start + timedelta(hours=duration)
        location = parsed.get("location")

        try:
            event = await google.create_event(
                title=title,
                start=start,
                end=end,
                location=location,
            )
            event_link = event.get("htmlLink", "")
            return SkillResult(
                response_text=(
                    f"✅ Создано: <b>{title}</b>\n"
                    f"📅 {start.strftime('%d.%m.%Y %H:%M')} — "
                    f"{end.strftime('%H:%M')}\n"
                    f"{f'📍 {location}' if location else ''}"
                    f"{f'\n🔗 {event_link}' if event_link else ''}"
                )
            )
        except Exception as e:
            logger.error("Calendar create_event failed: %s", e)
            return SkillResult(
                response_text=f"Ошибка при создании события «{title}». Попробуйте позже."
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return CREATE_EVENT_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _extract_event_details(
    title: str, dt: str, user_text: str, language: str
) -> str:
    """Extract event details as JSON via LLM."""
    client = anthropic_client()
    system = CREATE_EVENT_SYSTEM_PROMPT.format(language=language or "ru")
    prompt = f"Title hint: {title}\nDatetime hint: {dt}\nUser said: {user_text}"
    prompt_data = PromptAdapter.for_claude(
        system=system, messages=[{"role": "user", "content": prompt}]
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=256, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Create event LLM failed: %s", e)
        return "{}"


skill = CreateEventSkill()
