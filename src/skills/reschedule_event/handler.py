"""Reschedule event skill — moves calendar events using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

RESCHEDULE_SYSTEM_PROMPT = """\
You are a calendar assistant. The user wants to move or reschedule an event.

Rules:
- Confirm the change: "Moved <b>[Title]</b> to [New Day] [New Time]."
- Check for conflicts: "No conflicts" or "Heads up — you have [X] at that time."
- If the event is ambiguous, ask which one (max 1 question).
- Use HTML tags for Telegram. No Markdown.
- Respond in: {language}."""


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
        query = message.text or ""
        result = await reschedule_response(query, context.language or "en")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return RESCHEDULE_SYSTEM_PROMPT.format(language=context.language or "en")


async def reschedule_response(query: str, language: str) -> str:
    """Generate reschedule confirmation using Claude Haiku."""
    client = anthropic_client()
    system = RESCHEDULE_SYSTEM_PROMPT.format(language=language)
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
        logger.warning("Reschedule event failed: %s", e)
        return "I couldn't reschedule the event. Try again?"


skill = RescheduleEventSkill()
