"""Compare options skill — structured comparison using Claude Sonnet."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

COMPARE_SYSTEM_PROMPT = """\
You are a comparison assistant. The user wants to compare options.

Rules:
- Structure the comparison with clear categories (cost, quality, etc.).
- Use bullet points. One line per point.
- Be balanced and factual. No bias unless the user asks for a recommendation.
- If the user asks "which is better?", give a bottom-line recommendation with reasoning.
- Max 10 lines. Dense and scannable.
- If comparing more than 4 items, ask the user to narrow down to 3-4.
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- Respond in the user's preferred language: {language}.
- If no preference is set, match the language of their message."""


class CompareOptionsSkill:
    name = "compare_options"
    intents = ["compare_options"]
    model = "claude-sonnet-4-5"

    @observe(name="compare_options")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = (
            intent_data.get("search_topic")
            or intent_data.get("search_query")
            or message.text
            or ""
        )
        query = query.strip()

        if not query:
            return SkillResult(
                response_text="What would you like me to compare?"
            )

        answer = await generate_comparison(query, context.language or "en")
        return SkillResult(response_text=answer)

    def get_system_prompt(self, context: SessionContext) -> str:
        return COMPARE_SYSTEM_PROMPT.format(
            language=context.language or "en"
        )


async def generate_comparison(query: str, language: str) -> str:
    """Generate a structured comparison using Claude Sonnet."""
    client = anthropic_client()
    system = COMPARE_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": query}],
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            **prompt_data,
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Claude comparison failed: %s", e)
        return "I couldn't generate the comparison. Try rephrasing?"


skill = CompareOptionsSkill()
