"""Morning brief skill — combines real email + calendar data into daily summary."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, parse_email_headers, require_google_or_prompt
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MORNING_BRIEF_SYSTEM_PROMPT = """\
You are a life assistant generating a morning brief.

You will receive real email and calendar data. Use it to create the brief.

Rules:
- Start with "Доброе утро!" (or equivalent).
- Section 1: Today's events with times (bullet points).
- Section 2: Important unread emails (max 3).
- If nothing scheduled, say "Календарь свободен."
- If no emails, say "Нет важных писем."
- End with one actionable suggestion.
- Keep it scannable — short lines, no dense paragraphs.
- Use HTML tags for Telegram (<b>bold</b>). No Markdown.
- Max 8 bullet points total.
- Respond in: {language}."""


class MorningBriefSkill:
    name = "morning_brief"
    intents = ["morning_brief"]
    model = "claude-haiku-4-5"

    @observe(name="morning_brief")
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
            return SkillResult(response_text="Ошибка подключения к Google. Попробуйте /connect")

        # Fetch today's events and unread emails in parallel
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        events_text = "Нет событий на сегодня."
        emails_text = "Нет непрочитанных писем."

        try:
            events = await google.list_events(today_start, today_end)
            if events:
                events_text = "\n".join(
                    f"• {e.get('start', {}).get('dateTime', '?')}: "
                    f"{e.get('summary', '(без названия)')}"
                    for e in events[:8]
                )
        except Exception as e:
            logger.warning("Morning brief calendar failed: %s", e)
            events_text = "Не удалось загрузить календарь."

        try:
            messages = await google.list_messages("is:unread", max_results=5)
            if messages:
                parsed = [parse_email_headers(m) for m in messages]
                emails_text = "\n".join(
                    f"• {e['from']}: {e['subject']}" for e in parsed[:5]
                )
        except Exception as e:
            logger.warning("Morning brief email failed: %s", e)
            emails_text = "Не удалось загрузить почту."

        combined = (
            f"Today's calendar events:\n{events_text}\n\n"
            f"Unread emails:\n{emails_text}"
        )

        result = await _generate_brief(combined, context.language or "ru")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return MORNING_BRIEF_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _generate_brief(data: str, language: str) -> str:
    """Generate morning brief from real data using LLM."""
    client = anthropic_client()
    system = MORNING_BRIEF_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": data}],
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=1024, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Morning brief LLM failed: %s", e)
        return "Не удалось подготовить утренний обзор."


skill = MorningBriefSkill()
