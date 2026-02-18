"""Draft reply skill — fetches real email thread, drafts reply via LLM."""

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

DRAFT_REPLY_SYSTEM_PROMPT = """\
You are an email assistant. The user wants to reply to an email.

You will receive the email thread. Draft a reply based on the user's instructions.

Rules:
- Match the tone of the original email (formal replies to formal emails).
- Keep it concise — reply to the point, not the whole thread.
- Output ONLY the reply text. No headers, no formatting.
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
        prompt_result = await require_google_or_prompt(context.user_id)
        if prompt_result:
            return prompt_result

        google = await get_google_client(context.user_id)
        if not google:
            return SkillResult(response_text="Ошибка подключения к Gmail. Попробуйте /connect")

        # Try to find the thread to reply to — use most recent unread
        try:
            messages = await google.list_messages("is:unread", max_results=1)
            if not messages:
                return SkillResult(response_text="Нет непрочитанных писем для ответа.")

            thread_id = messages[0].get("threadId", "")
            if thread_id:
                thread_msgs = await google.get_thread(thread_id)
            else:
                thread_msgs = messages
        except Exception as e:
            logger.warning("Gmail fetch thread failed: %s", e)
            return SkillResult(response_text="Ошибка при загрузке письма. Попробуйте позже.")

        # Format thread for LLM
        parsed = [parse_email_headers(m) for m in thread_msgs]
        thread_text = "\n---\n".join(
            f"From: {e['from']}\nSubject: {e['subject']}\n{e['snippet']}" for e in parsed
        )

        user_instruction = message.text or "draft a reply"

        # LLM drafts reply
        draft = await _draft_reply(thread_text, user_instruction, context.language)

        original = parsed[-1] if parsed else {}
        return SkillResult(
            response_text=(
                f"<b>Черновик ответа на:</b> {original.get('subject', '')}\n"
                f"<b>От:</b> {original.get('from', '')}\n\n"
                f"{draft}\n\n"
                f"<i>Отредактируйте и отправьте через «напиши email ...»</i>"
            )
        )

    def get_system_prompt(self, context: SessionContext) -> str:
        return DRAFT_REPLY_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _draft_reply(thread_text: str, instruction: str, language: str) -> str:
    """Draft reply using LLM with real thread context."""
    client = anthropic_client()
    system = DRAFT_REPLY_SYSTEM_PROMPT.format(language=language or "ru")
    prompt = f"Email thread:\n{thread_text}\n\nUser instruction: {instruction}\n\nDraft reply:"
    prompt_data = PromptAdapter.for_claude(
        system=system, messages=[{"role": "user", "content": prompt}]
    )
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024, **prompt_data
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Draft reply LLM failed: %s", e)
        return "Не удалось составить ответ."


skill = DraftReplySkill()
