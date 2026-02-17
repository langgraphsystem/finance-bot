"""Send email skill — composes and sends email (with approval) using Claude Sonnet."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SEND_EMAIL_SYSTEM_PROMPT = """\
You are an email assistant. The user wants to compose and send an email.

Rules:
- Draft the email with To, Subject, and Body clearly separated.
- Match the tone to the context (professional, casual, empathetic).
- Show the draft first, then ask "Send this?" — NEVER send without confirmation.
- Format with HTML tags for Telegram (<b>bold</b>). No Markdown.
- Keep emails concise — 3-5 sentences for business, 1-3 for personal.
- Respond in: {language}."""


class SendEmailSkill:
    name = "send_email"
    intents = ["send_email"]
    model = "claude-sonnet-4-5"

    @observe(name="send_email")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        email_to = intent_data.get("email_to") or ""
        email_subject = intent_data.get("email_subject") or ""
        email_body_hint = intent_data.get("email_body_hint") or ""
        query = message.text or ""
        prompt = (
            f"Compose email. To: {email_to}. Subject: {email_subject}. "
            f"Hint: {email_body_hint}. User said: {query}"
        )

        draft = await compose_email(prompt.strip(), context.language or "en")
        return SkillResult(response_text=draft)

    def get_system_prompt(self, context: SessionContext) -> str:
        return SEND_EMAIL_SYSTEM_PROMPT.format(language=context.language or "en")


async def compose_email(query: str, language: str) -> str:
    """Compose email draft using Claude Sonnet."""
    client = anthropic_client()
    system = SEND_EMAIL_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": query}],
    )
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1024, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Compose email failed: %s", e)
        return "I couldn't compose the email. Try again?"


skill = SendEmailSkill()
