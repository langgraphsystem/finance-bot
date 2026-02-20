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

CHAT_SYSTEM_PROMPT = """Ты — AI-помощник для финансов и жизни в Telegram.

Вот что ты умеешь:
<b>💰 Финансы:</b> расходы, доходы, чеки, бюджеты, аналитика, отчёты PDF
<b>📧 Почта:</b> проверить входящие, отправить email, ответить, найти неотвеченные
<b>📅 Календарь:</b> расписание, создать событие, перенести, найти свободное время
<b>📝 Заметки:</b> идеи, задачи, напоминания, план дня, рефлексия
<b>🍽 Трекинг:</b> еда, напитки, настроение, сон
<b>🔍 Поиск:</b> ответы на вопросы, поиск в интернете, сравнение вариантов
<b>✍️ Тексты:</b> написать письмо, пост, перевод, проверка грамматики

Правила:
- На приветствие отвечай дружелюбно и КРАТКО (1-2 предложения): поздоровайся \
и спроси чем помочь. НЕ спрашивай о роде деятельности, НЕ спрашивай что \
нужно отслеживать, НЕ проводи онбординг — пользователь уже зарегистрирован. \
Пример: «Привет! Чем могу помочь?»
- Если пользователь спрашивает что ты умеешь — покажи список возможностей.
- На любые вопросы отвечай полезно и по делу. Ты умный помощник — \
отвечай на вопросы про что угодно, помогай с информацией, советами.
- Если запрос связан с функцией бота, можешь в конце ответа мягко \
подсказать: «Кстати, я могу сделать это за вас — просто напишите ...»
- НЕ используй эмодзи если пользователь их не использует.

Форматирование: HTML-теги для Telegram (<b>, <i>, <code>).
НЕ используй Markdown. Списки через • (bullet).
Ответ короткий (3-6 предложений макс)."""


class GeneralChatSkill:
    name = "general_chat"
    intents = ["general_chat"]
    model = "gpt-5.2"

    def _get_dosing_prompt(self, suppress: bool) -> str:
        """Return system prompt with or without feature suggestions."""
        if suppress:
            return CHAT_SYSTEM_PROMPT.replace(
                "можешь в конце ответа мягко "
                "подсказать: «Кстати, я могу сделать это "
                "за вас — просто напишите ...»",
                "НЕ добавляй подсказки о возможностях бота — пользователь уже знает что ты умеешь",
            )
        return CHAT_SYSTEM_PROMPT

    @observe(name="general_chat")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        from src.core.memory import sliding_window

        # Check if user has seen too many suggestions recently
        recent_chat_count = await sliding_window.count_recent_intents(
            context.user_id, "general_chat", last_n=6
        )
        suppress_suggestions = recent_chat_count >= 3
        system_prompt = self._get_dosing_prompt(suppress_suggestions)

        client = anthropic_client()
        assembled = intent_data.get("_assembled")

        if assembled:
            # Use assembled context: enriched system prompt + history
            if suppress_suggestions:
                asm_prompt = assembled.system_prompt.replace(
                    "можешь в конце ответа мягко "
                    "подсказать: «Кстати, я могу сделать "
                    "это за вас — просто напишите ...»",
                    "НЕ добавляй подсказки о возможностях бота — пользователь уже знает",
                )
            else:
                asm_prompt = assembled.system_prompt
            non_system = [
                m for m in assembled.messages if m["role"] != "system" and m.get("content")
            ]
            if not non_system:
                non_system = [{"role": "user", "content": message.text or "Привет"}]
            prompt_data = PromptAdapter.for_claude(
                system=asm_prompt,
                messages=non_system,
            )
        else:
            # Fallback: direct call without assembled context
            user_text = message.text or "Привет"
            prompt_data = PromptAdapter.for_claude(
                system=system_prompt,
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
