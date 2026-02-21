"""Send email skill — composes email via LLM, sends via Composio Gmail."""

import logging
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

        # Store pending action — require user confirmation before sending
        from src.core.pending_actions import store_pending_action

        pending_id = await store_pending_action(
            intent="send_email",
            user_id=context.user_id,
            family_id=context.family_id,
            action_data={
                "email_to": email_to,
                "email_subject": email_subject or "No Subject",
                "email_body": body,
            },
        )

        preview = (
            f"<b>Черновик email:</b>\n\n"
            f"<b>To:</b> {email_to}\n"
            f"<b>Subject:</b> {email_subject or 'No Subject'}\n\n"
            f"{body[:500]}"
        )

        return SkillResult(
            response_text=preview,
            buttons=[
                {
                    "text": "📨 Отправить",
                    "callback": f"confirm_action:{pending_id}",
                },
                {
                    "text": "❌ Отмена",
                    "callback": f"cancel_action:{pending_id}",
                },
            ],
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return SEND_EMAIL_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _draft_body(to: str, subject: str, hint: str, user_text: str, language: str) -> str:
    """Draft email body using LLM."""
    client = anthropic_client()
    system = SEND_EMAIL_SYSTEM_PROMPT.format(language=language or "ru")
    prompt = (
        f"Compose email body.\nTo: {to}\nSubject: {subject}\nHint: {hint}\nUser said: {user_text}"
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


async def execute_send(action_data: dict, user_id: str) -> str:
    """Actually send the email via Composio Gmail. Called after user confirms."""
    google = await get_google_client(user_id)
    if not google:
        return "Ошибка подключения к Gmail. Попробуйте /connect"

    try:
        await google.send_message(
            to=action_data["email_to"],
            subject=action_data["email_subject"],
            body=action_data["email_body"],
        )
    except Exception as e:
        logger.error("Gmail send failed: %s", e)
        return "Не удалось отправить email. Попробуйте позже."

    return (
        f"✅ Email отправлен!\n\n"
        f"<b>To:</b> {action_data['email_to']}\n"
        f"<b>Subject:</b> {action_data['email_subject']}"
    )


skill = SendEmailSkill()
