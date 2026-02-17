"""Follow-up email skill — finds unanswered emails using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

FOLLOW_UP_SYSTEM_PROMPT = """\
You are an email assistant. The user wants to check for emails they haven't replied to.

Rules:
- List unanswered important emails: "[Sender] — [Subject] (received [time ago])"
- Sort by oldest first (most urgent to reply).
- Skip newsletters, promotions, automated messages.
- If none, say "You're all caught up — no pending replies."
- End with "Want me to draft a reply to any of these?"
- Use HTML tags for Telegram (<b>bold</b>). No Markdown.
- Respond in: {language}."""


class FollowUpEmailSkill:
    name = "follow_up_email"
    intents = ["follow_up_email"]
    model = "claude-haiku-4-5"

    @observe(name="follow_up_email")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = message.text or "any emails I need to reply to?"
        result = await check_follow_ups(query, context.language or "en")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return FOLLOW_UP_SYSTEM_PROMPT.format(language=context.language or "en")


async def check_follow_ups(query: str, language: str) -> str:
    """Check for follow-up emails using Claude Haiku."""
    client = anthropic_client()
    system = FOLLOW_UP_SYSTEM_PROMPT.format(language=language)
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
        logger.warning("Follow-up check failed: %s", e)
        return "I couldn't check your follow-ups. Try again?"


skill = FollowUpEmailSkill()
