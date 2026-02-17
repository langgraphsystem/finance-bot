"""Create event skill — adds calendar events using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

CREATE_EVENT_SYSTEM_PROMPT = """\
You are a calendar assistant. The user wants to create an event.

Rules:
- Confirm the event with: title, date, time, duration (default 1 hour if unspecified).
- If location is mentioned, include it.
- Format: "Created: <b>[Title]</b> — [Day] [Time]. [Duration]."
- If info is ambiguous, ask one clarifying question (max 1).
- End with "That work?" to invite correction.
- Use HTML tags for Telegram. No Markdown.
- Respond in: {language}."""


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
        event_title = intent_data.get("event_title") or ""
        event_datetime = intent_data.get("event_datetime") or ""
        query = message.text or ""
        prompt = f"Create event: {event_title} at {event_datetime}. User said: {query}"

        result = await create_event_response(prompt.strip(), context.language or "en")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return CREATE_EVENT_SYSTEM_PROMPT.format(language=context.language or "en")


async def create_event_response(query: str, language: str) -> str:
    """Generate event creation confirmation using Claude Haiku."""
    client = anthropic_client()
    system = CREATE_EVENT_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": query}],
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=512, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Create event failed: %s", e)
        return "I couldn't create the event. Try again?"


skill = CreateEventSkill()
