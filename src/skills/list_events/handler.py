"""List events skill — fetches real calendar events via Google Calendar API."""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

LIST_EVENTS_SYSTEM_PROMPT = """\
You are a calendar assistant. Format the user's schedule clearly using Telegram HTML.

Rules:
- Group events by day if multiple days.
- Use bullet points with time and title: • 9:00 AM — Event title
- Show free gaps between events.
- If no events, say "Ваш календарь свободен."
- End with an action offer: "Запланировать что-нибудь?"
- Respond in: {language}."""


class ListEventsSkill:
    name = "list_events"
    intents = ["list_events"]
    model = "claude-haiku-4-5"

    @observe(name="list_events")
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

        # Use user's local timezone for "today" boundaries
        tz = ZoneInfo(context.timezone)
        now_local = datetime.now(tz)
        time_min = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + timedelta(days=1)

        period = intent_data.get("period", "today")
        if period == "week":
            time_max = time_min + timedelta(days=7)
        elif period == "month":
            time_max = time_min + timedelta(days=30)

        try:
            events = await google.list_events(time_min, time_max)
        except Exception as e:
            logger.warning("Calendar list_events failed: %s", e)
            return SkillResult(response_text="Ошибка при загрузке календаря.")

        if not events:
            return SkillResult(response_text="📅 Ваш календарь свободен. Запланировать что-нибудь?")

        # Format events for LLM
        event_text = "\n".join(
            f"- {e.get('start', {}).get('dateTime', e.get('start', {}).get('date', ''))}: "
            f"{e.get('summary', '(без названия)')}"
            f"{' @ ' + e.get('location', '') if e.get('location') else ''}"
            for e in events
        )

        result = await _format_events(event_text, context.language or "ru")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return LIST_EVENTS_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _format_events(event_data: str, language: str) -> str:
    """Format calendar events using LLM."""
    client = anthropic_client()
    system = LIST_EVENTS_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": f"My events:\n{event_data}"}],
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=1024, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("List events LLM failed: %s", e)
        return "Не удалось отформатировать расписание."


skill = ListEventsSkill()
