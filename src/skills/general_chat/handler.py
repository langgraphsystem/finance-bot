"""General chat skill — fallback for non-financial queries."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = """Ты — финансовый помощник в Telegram.
Если вопрос не связан с финансами, вежливо перенаправь:
"Я финансовый помощник, могу помочь с учётом расходов и доходов."

Если вопрос частично связан, ответь кратко и предложи:
- Записать расход/доход
- Посмотреть статистику
- Отсканировать чек

Форматирование: используй HTML-теги для Telegram (<b>жирный</b>, <i>курсив</i>, <code>код</code>).
НЕ используй Markdown (**, *, ```). Списки оформляй через • (bullet)."""


class GeneralChatSkill:
    name = "general_chat"
    intents = ["general_chat"]
    model = "claude-haiku-4-5"

    @observe(name="general_chat")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        client = anthropic_client()
        assembled = intent_data.get("_assembled")

        if assembled:
            # Use assembled context: enriched system prompt + history + memories
            non_system = [
                m for m in assembled.messages if m["role"] != "system" and m.get("content")
            ]
            if not non_system:
                non_system = [{"role": "user", "content": message.text or "Привет"}]
            prompt_data = PromptAdapter.for_claude(
                system=assembled.system_prompt,
                messages=non_system,
            )
        else:
            # Fallback: direct call without assembled context
            user_text = message.text or "Привет"
            prompt_data = PromptAdapter.for_claude(
                system=CHAT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_text}],
            )

        response = await client.messages.create(
            model=self.model,
            max_tokens=1024,
            **prompt_data,
        )
        return SkillResult(response_text=response.content[0].text)

    def get_system_prompt(self, context: SessionContext) -> str:
        return CHAT_SYSTEM_PROMPT


skill = GeneralChatSkill()
