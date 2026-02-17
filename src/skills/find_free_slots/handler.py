"""Find free slots skill — checks available times using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

FREE_SLOTS_SYSTEM_PROMPT = """\
You are a calendar assistant. The user wants to know when they're free.

Rules:
- List free time blocks with start-end times.
- Business hours default: 8 AM — 6 PM (unless user specifies otherwise).
- Format: "You're free: [time range], [time range]."
- If the whole day is free, say so.
- Offer to schedule: "Want to book something?"
- Use HTML tags for Telegram. No Markdown.
- Respond in: {language}."""


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
        query = message.text or "when am I free this week?"
        result = await find_free_response(query, context.language or "en")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return FREE_SLOTS_SYSTEM_PROMPT.format(language=context.language or "en")


async def find_free_response(query: str, language: str) -> str:
    """Generate free slots response using Claude Haiku."""
    client = anthropic_client()
    system = FREE_SLOTS_SYSTEM_PROMPT.format(language=language)
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
        logger.warning("Find free slots failed: %s", e)
        return "I couldn't check your availability. Try again?"


skill = FindFreeSlotsSkill()
