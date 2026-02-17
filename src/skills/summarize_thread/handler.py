"""Summarize thread skill — summarizes email conversations using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SUMMARIZE_THREAD_SYSTEM_PROMPT = """\
You are an email assistant. Summarize an email thread concisely.

Rules:
- Start with a one-line summary of the thread topic.
- List key decisions or action items.
- Note who said what for important points.
- Max 5 sentences for the summary.
- End with "Any action needed on this?"
- Use HTML tags for Telegram (<b>bold</b>). No Markdown.
- Respond in: {language}."""


class SummarizeThreadSkill:
    name = "summarize_thread"
    intents = ["summarize_thread"]
    model = "claude-haiku-4-5"

    @observe(name="summarize_thread")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = message.text or "summarize this email thread"
        result = await summarize_thread(query, context.language or "en")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return SUMMARIZE_THREAD_SYSTEM_PROMPT.format(language=context.language or "en")


async def summarize_thread(query: str, language: str) -> str:
    """Summarize email thread using Claude Haiku."""
    client = anthropic_client()
    system = SUMMARIZE_THREAD_SYSTEM_PROMPT.format(language=language)
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
        logger.warning("Summarize thread failed: %s", e)
        return "I couldn't summarize the thread. Try again?"


skill = SummarizeThreadSkill()
