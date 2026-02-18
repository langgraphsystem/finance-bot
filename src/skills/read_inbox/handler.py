"""Read inbox skill — fetches real Gmail messages and summarizes with LLM."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, parse_email_headers, require_google_or_prompt
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
        # OAuth check
        prompt_result = await require_google_or_prompt(context.user_id)
        if prompt_result:
            return prompt_result

        google = await get_google_client(context.user_id)
        if not google:
            return SkillResult(
                response_text="Не удалось подключиться к Gmail. Попробуйте /connect"
            )

        # Fetch real emails
        try:
            messages = await google.list_messages("is:unread", max_results=10)
        except Exception as e:
            logger.warning("Gmail list_messages failed: %s", e)
            return SkillResult(response_text="Ошибка при загрузке почты. Попробуйте позже.")

        if not messages:
            return SkillResult(response_text="📭 Новых писем нет.")

        # Parse headers into readable format
        parsed = [parse_email_headers(m) for m in messages]
        email_text = "\n".join(
            f"{i}. From: {e['from']}\n   Subject: {e['subject']}\n   {e['snippet'][:100]}"
            for i, e in enumerate(parsed, 1)
        )

        # LLM summarizes real data
        result = await _summarize_with_llm(email_text, context.language or "ru")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return READ_INBOX_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _summarize_with_llm(email_data: str, language: str) -> str:
    """Summarize real email data using Claude Haiku."""
    client = anthropic_client()
    system = READ_INBOX_SYSTEM_PROMPT.format(language=language)
    prompt = f"Here are my unread emails:\n\n{email_data}\n\nSummarize them."
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=1024, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Read inbox LLM failed: %s", e)
        return "Не удалось обработать почту. Попробуйте позже."


skill = ReadInboxSkill()
