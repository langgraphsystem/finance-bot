"""Follow-up email skill — finds unanswered emails via real Gmail API."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, parse_email_headers, require_google_or_prompt
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

FOLLOW_UP_SYSTEM_PROMPT = """\
You are an email assistant analyzing unanswered emails.

Given a list of emails from the user's inbox, identify which ones need a reply.

Rules:
- List unanswered important emails: "[Sender] — [Subject] (received [time ago])"
- Sort by oldest first (most urgent to reply).
- Skip newsletters, promotions, automated messages.
- If none need replies, say "Вы в курсе — нет неотвеченных писем."
- End with "Ответить на какое-нибудь из них?"
- Use HTML tags for Telegram (<b>bold</b>). No Markdown.
- Respond in: {language}."""


class FollowUpEmailSkill:
    name = "follow_up_email"
    intents = ["follow_up_email"]
    model = "gpt-5.2"

    @observe(name="follow_up_email")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        prompt_result = await require_google_or_prompt(context.user_id)
        if prompt_result:
            return prompt_result

        google = await get_google_client(context.user_id)
        if not google:
            return SkillResult(response_text="Ошибка подключения к Gmail. Попробуйте /connect")

        try:
            messages = await google.list_messages("is:inbox is:unread", max_results=20)
        except Exception as e:
            logger.warning("Gmail follow-up query failed: %s", e)
            return SkillResult(response_text="Ошибка при загрузке почты.")

        if not messages:
            return SkillResult(response_text="✅ Нет неотвеченных писем — всё в порядке!")

        parsed = [parse_email_headers(m) for m in messages]
        email_text = "\n".join(
            f"{i}. From: {e['from']} | Subject: {e['subject']} | {e['snippet'][:80]}"
            for i, e in enumerate(parsed, 1)
        )

        result = await _analyze_follow_ups(email_text, context.language or "ru")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return FOLLOW_UP_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _analyze_follow_ups(email_data: str, language: str) -> str:
    """Analyze which emails need follow-up."""
    system = FOLLOW_UP_SYSTEM_PROMPT.format(language=language)
    try:
        return await generate_text(
            "gpt-5.2", system,
            [{"role": "user", "content": f"My unread emails:\n{email_data}"}],
            max_tokens=1024,
        )
    except Exception as e:
        logger.warning("Follow-up analysis failed: %s", e)
        return "Не удалось проанализировать почту."


skill = FollowUpEmailSkill()
