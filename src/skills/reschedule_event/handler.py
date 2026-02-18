"""Reschedule event skill — moves calendar events via Google Calendar API."""

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

RESCHEDULE_SYSTEM_PROMPT = """\
Extract the reschedule request from the user's message.

Respond with ONLY a JSON object:
{{"event_name": "...", "new_date": "YYYY-MM-DD", "new_time": "HH:MM"}}

If info is missing, set the field to null."""


class RescheduleEventSkill:
    name = "reschedule_event"
    intents = ["reschedule_event"]
    model = "claude-haiku-4-5"

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
        now = datetime.now(UTC)
        try:
            events = await google.list_events(now, now + timedelta(days=7))
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
                        f"• {e.get('summary', '?')} — "
                        f"{e.get('start', {}).get('dateTime', '')}"
                        for e in events[:5]
                    )
                    + "\n\nУкажите, какое событие перенести и на когда."
                )
            )

        event_id = parsed.get("event_id")
        new_date = parsed.get("new_date")
        new_time = parsed.get("new_time")

        if not event_id or not new_date:
            return SkillResult(
                response_text="Не удалось определить событие или новую дату. Уточните запрос."
            )

        try:
            time_str = new_time or "09:00"
            new_start = datetime.fromisoformat(f"{new_date}T{time_str}:00+00:00")
            new_end = new_start + timedelta(hours=1)

            await google.update_event(
                event_id,
                start={"dateTime": new_start.isoformat(), "timeZone": "UTC"},
                end={"dateTime": new_end.isoformat(), "timeZone": "UTC"},
            )
            return SkillResult(
                response_text=(
                    f"✅ Событие перенесено на "
                    f"{new_start.strftime('%d.%m.%Y %H:%M')}"
                )
            )
        except Exception as e:
            logger.error("Calendar update failed: %s", e)
            return SkillResult(response_text="Ошибка при переносе события.")

    def get_system_prompt(self, context: SessionContext) -> str:
        return RESCHEDULE_SYSTEM_PROMPT


async def _parse_reschedule(user_text: str, events_list: str, language: str) -> str:
    """Parse reschedule request via LLM, match to event."""
    client = anthropic_client()
    system = (
        "Match the user's reschedule request to one of these events and extract new time.\n"
        "Respond with JSON: {\"event_id\": \"...\", \"new_date\": \"YYYY-MM-DD\", "
        "\"new_time\": \"HH:MM\"}\n"
        f"Events:\n{events_list}"
    )
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=256, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Reschedule parse failed: %s", e)
        return "{}"


skill = RescheduleEventSkill()
