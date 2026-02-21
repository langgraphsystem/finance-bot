"""General chat skill — fallback for non-financial queries."""

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

# Fast-path: simple greetings answered without LLM
_GREETING_WORDS = frozenset({
    "привет", "здравствуй", "здравствуйте", "приветик", "хай", "хэй",
    "hi", "hello", "hey", "добрый день", "доброе утро", "добрый вечер",
    "йо", "yo", "здаров", "здарова", "прив", "ку", "хелло", "салам",
    "ола", "hola", "здрасте", "здрасьте", "приветствую",
})

_GREETINGS_MORNING = [
    "Доброе утро! Чем могу помочь?",
    "Утро доброе! Что нужно сделать?",
    "Доброе утро! Слушаю.",
]
_GREETINGS_DAY = [
    "Привет! Чем могу помочь?",
    "Привет! Что нужно?",
    "Добрый день! Слушаю.",
]
_GREETINGS_EVENING = [
    "Добрый вечер! Чем помочь?",
    "Привет! Что нужно сделать?",
    "Добрый вечер! Слушаю.",
]
_GREETINGS_NIGHT = [
    "Привет! Не спится? Чем помочь?",
    "Ещё не спишь? Чем могу помочь?",
    "Привет! Слушаю.",
]


def _is_greeting(text: str) -> bool:
    """Check if the message is a simple greeting."""
    return text.lower().strip().rstrip("!.?  ") in _GREETING_WORDS


def _time_greeting(tz_name: str) -> str:
    """Return a time-appropriate greeting."""
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.now(timezone(timedelta(hours=-5)))  # fallback EST
    hour = now.hour
    if 5 <= hour < 12:
        return random.choice(_GREETINGS_MORNING)
    if 12 <= hour < 18:
        return random.choice(_GREETINGS_DAY)
    if 18 <= hour < 23:
        return random.choice(_GREETINGS_EVENING)
    return random.choice(_GREETINGS_NIGHT)

CHAT_SYSTEM_PROMPT = """\
Ты — персональный AI-ассистент пользователя в Telegram.

Ты помогаешь с ЛЮБЫМ запросом: советы, объяснения, расчёты, \
мозговой штурм, рецепты, обучение, анализ ситуации, личные вопросы, \
планирование, творческие задачи — всё что угодно.

Также ты умеешь (подскажи если запрос похож на одну из функций):
• Финансы: расходы, доходы, чеки, бюджеты, аналитика, отчёты PDF
• Почта: проверить входящие, отправить email, ответить
• Календарь: расписание, создать событие, утренняя сводка
• Задачи: дела, напоминания, списки покупок
• Трекинг: еда, напитки, настроение, план дня, рефлексия
• Поиск: вопросы, интернет, сравнение, карты, YouTube
• Тексты: письма, посты, перевод, проверка грамматики
• Клиенты: бронирования, контакты

Принципы:
- Отвечай кратко — пользователь в мессенджере (3-6 предложений макс)
- Если нужны данные которых нет — скажи что именно нужно
- Не притворяйся что умеешь то чего не умеешь
- На приветствие — коротко поздоровайся и спроси чем помочь (1-2 предложения)
- Отвечай на языке пользователя
- Если запрос связан с функцией из списка выше, можешь мягко \
подсказать: «Кстати, я могу сделать это — просто напишите ...»

Форматирование: HTML-теги для Telegram (<b>, <i>, <code>).
НЕ используй Markdown. Списки через • (bullet)."""


class GeneralChatSkill:
    name = "general_chat"
    intents = ["general_chat"]
    model = "claude-sonnet-4-6"

    def _get_dosing_prompt(self, suppress: bool) -> str:
        """Return system prompt with or without feature suggestions."""
        if suppress:
            return CHAT_SYSTEM_PROMPT.replace(
                "можешь мягко "
                "подсказать: «Кстати, я могу сделать это "
                "— просто напишите ...»",
                "НЕ добавляй подсказки о возможностях "
                "— пользователь уже знает что ты умеешь",
            )
        return CHAT_SYSTEM_PROMPT

    @observe(name="general_chat")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        # Fast-path: simple greetings — no LLM needed
        text_raw = (message.text or "").strip()
        if text_raw and _is_greeting(text_raw):
            return SkillResult(response_text=_time_greeting(context.timezone))

        from src.core.memory import sliding_window

        # Log if this is a redirect from low-confidence intent
        original = intent_data.get("original_intent")
        if original:
            logger.info(
                "general_chat fallback from intent=%s conf=%.2f",
                original,
                intent_data.get("confidence", 0),
            )

        # Check if user has seen too many suggestions recently
        recent_chat_count = await sliding_window.count_recent_intents(
            context.user_id, "general_chat", last_n=6
        )
        suppress_suggestions = recent_chat_count >= 3
        system_prompt = self._get_dosing_prompt(suppress_suggestions)

        assembled = intent_data.get("_assembled")

        if assembled:
            # Preserve assembled history, but keep GeneralChat's own prompt rules.
            # Otherwise agent-level prompts (e.g. onboarding) can override greeting behavior.
            sys = system_prompt
            msgs = [
                m for m in assembled.messages if m["role"] != "system" and m.get("content")
            ]
            if not msgs:
                msgs = [{"role": "user", "content": message.text or "Привет"}]
        else:
            sys = system_prompt
            msgs = [{"role": "user", "content": message.text or "Привет"}]

        text = await generate_text(self.model, sys, msgs, max_tokens=1024)
        return SkillResult(response_text=text)

    def get_system_prompt(self, context: SessionContext) -> str:
        return CHAT_SYSTEM_PROMPT


skill = GeneralChatSkill()
