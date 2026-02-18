"""Draft reply skill — replies to email threads using Claude Sonnet."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DRAFT_REPLY_SYSTEM_PROMPT = """\
You are an email assistant. The user wants to reply to an email.

Rules:
- Draft a reply based on the user's instructions.
- Match the tone of the original email (formal replies to formal emails).
- Show the draft first, then ask "Send this?"
- Keep it concise — reply to the point, not the whole thread.
- Format with HTML tags for Telegram (<b>bold</b>). No Markdown.
- Respond in: {language}."""


class DraftReplySkill:
    name = "draft_reply"
    intents = ["draft_reply"]
    model = "claude-sonnet-4-6"

    @observe(name="draft_reply")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = message.text or ""
        draft = await draft_reply_response(query, context.language or "en")
        return SkillResult(response_text=draft)

    def get_system_prompt(self, context: SessionContext) -> str:
        return DRAFT_REPLY_SYSTEM_PROMPT.format(language=context.language or "en")


async def draft_reply_response(query: str, language: str) -> str:
    """Draft email reply using Claude Sonnet."""
    client = anthropic_client()
    system = DRAFT_REPLY_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": query}],
    )
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Draft reply failed: %s", e)
        return "I couldn't draft the reply. Try again?"


skill = DraftReplySkill()
