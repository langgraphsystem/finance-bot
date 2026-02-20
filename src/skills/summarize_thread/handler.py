"""Summarize thread skill — fetches real email thread, summarizes with LLM."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.google_auth import get_google_client, parse_email_headers, require_google_or_prompt
from src.core.llm.clients import generate_text
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
- End with "Нужно что-то сделать по этому письму?"
- Use HTML tags for Telegram (<b>bold</b>). No Markdown.
- Respond in: {language}."""


class SummarizeThreadSkill:
    name = "summarize_thread"
    intents = ["summarize_thread"]
    model = "gpt-5.2"

    @observe(name="summarize_thread")
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

        # Get most recent thread
        try:
            messages = await google.list_messages("is:inbox", max_results=1)
            if not messages:
                return SkillResult(response_text="Нет писем для суммаризации.")

            thread_id = messages[0].get("threadId", "")
            thread_msgs = await google.get_thread(thread_id) if thread_id else messages
        except Exception as e:
            logger.warning("Gmail thread fetch failed: %s", e)
            return SkillResult(response_text="Ошибка при загрузке цепочки писем.")

        parsed = [parse_email_headers(m) for m in thread_msgs]
        thread_text = "\n---\n".join(
            f"From: {e['from']}\nSubject: {e['subject']}\n{e['snippet']}" for e in parsed
        )

        result = await _summarize(thread_text, context.language or "ru")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return SUMMARIZE_THREAD_SYSTEM_PROMPT.format(language=context.language or "ru")


async def _summarize(thread_text: str, language: str) -> str:
    """Summarize email thread using LLM."""
    system = SUMMARIZE_THREAD_SYSTEM_PROMPT.format(language=language)
    try:
        return await generate_text(
            "gpt-5.2", system,
            [{"role": "user", "content": f"Email thread:\n{thread_text}"}],
            max_tokens=1024,
        )
    except Exception as e:
        logger.warning("Summarize thread LLM failed: %s", e)
        return "Не удалось обобщить цепочку писем."


skill = SummarizeThreadSkill()
