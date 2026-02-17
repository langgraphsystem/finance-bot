"""Morning brief skill — daily summary of calendar + tasks using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

MORNING_BRIEF_SYSTEM_PROMPT = """\
You are a life assistant generating a morning brief.

Rules:
- Start with "Morning!" (or equivalent in user's language).
- List today's events with times using bullet points.
- List tasks due today.
- If nothing is scheduled, say "No events today — your calendar is clear."
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
        query = message.text or "morning brief"
        brief = await generate_brief(query, context.language or "en")
        return SkillResult(response_text=brief)

    def get_system_prompt(self, context: SessionContext) -> str:
        return MORNING_BRIEF_SYSTEM_PROMPT.format(language=context.language or "en")


async def generate_brief(query: str, language: str) -> str:
    """Generate morning brief using Claude Haiku."""
    client = anthropic_client()
    system = MORNING_BRIEF_SYSTEM_PROMPT.format(language=language)
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
        logger.warning("Morning brief failed: %s", e)
        return "I couldn't prepare your morning brief. Try again?"


skill = MorningBriefSkill()
