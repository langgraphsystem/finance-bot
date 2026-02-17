"""Read inbox skill — summarizes important emails using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

READ_INBOX_SYSTEM_PROMPT = """\
You are an email assistant. Summarize the user's important emails.

Rules:
- Filter out promotions, newsletters, and spam.
- List important emails numbered: 1. [Sender] — [Subject summary]
- Group by urgency: needs reply first, then FYI.
- Max 7 items. If more, say "and X more."
- End with "Need me to reply to any of these?"
- Use HTML tags for Telegram (<b>bold</b>). No Markdown.
- Respond in: {language}."""


class ReadInboxSkill:
    name = "read_inbox"
    intents = ["read_inbox"]
    model = "claude-haiku-4-5"

    @observe(name="read_inbox")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = message.text or "check my email"
        result = await summarize_inbox(query, context.language or "en")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return READ_INBOX_SYSTEM_PROMPT.format(language=context.language or "en")


async def summarize_inbox(query: str, language: str) -> str:
    """Summarize inbox using Claude Haiku."""
    client = anthropic_client()
    system = READ_INBOX_SYSTEM_PROMPT.format(language=language)
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
        logger.warning("Read inbox failed: %s", e)
        return "I couldn't check your email. Try again?"


skill = ReadInboxSkill()
