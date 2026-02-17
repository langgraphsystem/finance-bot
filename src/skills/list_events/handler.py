"""List events skill — shows schedule for a date range using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
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
- If no events, say "Your calendar is clear."
- End with an action offer: "Want to schedule something?"
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
        query = message.text or "today's schedule"
        formatted = await format_events(query, context.language or "en")
        return SkillResult(response_text=formatted)

    def get_system_prompt(self, context: SessionContext) -> str:
        return LIST_EVENTS_SYSTEM_PROMPT.format(language=context.language or "en")


async def format_events(query: str, language: str) -> str:
    """Format calendar events using Claude Haiku."""
    client = anthropic_client()
    system = LIST_EVENTS_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": query}],
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=1024, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("List events failed: %s", e)
        return "I couldn't load your calendar. Try again?"


skill = ListEventsSkill()
