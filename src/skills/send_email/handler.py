"""Send email skill — composes email via LLM, sends via Gmail API."""

import base64
import logging
from email.mime.text import MIMEText
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, require_google_or_prompt
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

SEND_EMAIL_SYSTEM_PROMPT = """\
You are an email assistant. The user wants to compose and send an email.

Rules:
- Draft the email body only (no To/Subject headers — those are separate).
- Match the tone to the context (professional, casual, empathetic).
- Keep emails concise — 3-5 sentences for business, 1-3 for personal.
- Output ONLY the email body text, no HTML tags, no formatting instructions.
- Respond in: {language}."""


class SendEmailSkill:
    name = "send_email"
    intents = ["send_email"]
    model = "claude-sonnet-4-6"

    @observe(name="send_email")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        # OAuth check
        prompt_result = await require_google_or_prompt(context.user_id)
        if prompt_result:
            return prompt_result

        email_to = intent_data.get("email_to") or ""
        email_subject = intent_data.get("email_subject") or ""
        email_body_hint = intent_data.get("email_body_hint") or ""
        query = message.text or ""

        if not email_to:
            return SkillResult(
                response_text="Укажите получателя. Например: «напиши email john@example.com ...»"
            )

        # Draft the email body via LLM
        body = await _draft_body(email_to, email_subject, email_body_hint, query, context.language)

        # Build MIME message and send
        google = await get_google_client(context.user_id)
        if not google:
            return SkillResult(response_text="Ошибка подключения к Gmail. Попробуйте /connect")

        try:
            mime_msg = MIMEText(body)
            mime_msg["to"] = email_to
            mime_msg["subject"] = email_subject or "No Subject"
            raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
            await google.send_message(raw)
        except Exception as e:
            logger.error("Gmail send failed: %s", e)
            return SkillResult(
                response_text=(
                    f"Не удалось отправить. Вот черновик:\n\n"
                    f"<b>To:</b> {email_to}\n"
                    f"<b>Subject:</b> {email_subject}\n\n"
                    f"{body}"
                )
            )

        return SkillResult(
            response_text=(
                f"✅ Email отправлен!\n\n"
                f"<b>To:</b> {email_to}\n"
                f"<b>Subject:</b> {email_subject}"
            )
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SEND_EMAIL_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _draft_body(
    to: str, subject: str, hint: str, user_text: str, language: str
) -> str:
    """Draft email body using LLM."""
    client = anthropic_client()
    system = SEND_EMAIL_SYSTEM_PROMPT.format(language=language or "ru")
    prompt = (
        f"Compose email body.\nTo: {to}\nSubject: {subject}\n"
        f"Hint: {hint}\nUser said: {user_text}"
    )
    prompt_data = PromptAdapter.for_claude(
        system=system, messages=[{"role": "user", "content": prompt}]
    )
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Email draft failed: %s", e)
        return hint or user_text or "Hello,"


skill = SendEmailSkill()
