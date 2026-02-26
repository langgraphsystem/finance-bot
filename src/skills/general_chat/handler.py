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

_GREETINGS = {
    "en": {
        "morning": ["Good morning! How can I help?", "Morning! What do you need?"],
        "day": ["Hi! How can I help?", "Hey! What do you need?"],
        "evening": ["Good evening! How can I help?", "Hey! What can I do for you?"],
        "night": ["Hey! Can't sleep? How can I help?", "Hi! What do you need?"],
    },
    "ru": {
        "morning": ["Доброе утро! Чем могу помочь?", "Утро доброе! Что нужно сделать?"],
        "day": ["Привет! Чем могу помочь?", "Добрый день! Слушаю."],
        "evening": ["Добрый вечер! Чем помочь?", "Добрый вечер! Слушаю."],
        "night": ["Привет! Не спится? Чем помочь?", "Привет! Слушаю."],
    },
    "es": {
        "morning": ["Buenos dias! En que puedo ayudar?", "Buen dia! Que necesitas?"],
        "day": ["Hola! En que puedo ayudar?", "Hola! Que necesitas?"],
        "evening": ["Buenas tardes! En que puedo ayudar?", "Hola! Que puedo hacer?"],
        "night": ["Hola! En que puedo ayudar?", "Hola! Que necesitas?"],
    },
}

# Russian greeting words to detect user language from greeting itself
_RU_GREETING_WORDS = frozenset({
    "привет", "здравствуй", "здравствуйте", "приветик", "хай", "хэй",
    "добрый день", "доброе утро", "добрый вечер", "йо", "здаров",
    "здарова", "прив", "ку", "хелло", "салам", "здрасте", "здрасьте",
    "приветствую",
})
_ES_GREETING_WORDS = frozenset({"hola", "ола"})


def _is_greeting(text: str) -> bool:
    """Check if the message is a simple greeting."""
    return text.lower().strip().rstrip("!.?  ") in _GREETING_WORDS


def _detect_greeting_lang(text: str, context_lang: str | None) -> str:
    """Detect language from greeting word, falling back to context language."""
    word = text.lower().strip().rstrip("!.?  ")
    if word in _RU_GREETING_WORDS:
        return "ru"
    if word in _ES_GREETING_WORDS:
        return "es"
    # English greetings or unknown → use context language
    if context_lang and context_lang.startswith("ru"):
        return "ru"
    if context_lang and context_lang.startswith("es"):
        return "es"
    return "en"


def _time_greeting(tz_name: str, language: str = "en") -> str:
    """Return a time-appropriate greeting in the user's language."""
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.now(timezone(timedelta(hours=-5)))  # fallback EST
    hour = now.hour
    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 18:
        period = "day"
    elif 18 <= hour < 23:
        period = "evening"
    else:
        period = "night"
    greetings = _GREETINGS.get(language, _GREETINGS["en"])
    return random.choice(greetings[period])

CHAT_SYSTEM_PROMPT = """\
You are a personal AI assistant in Telegram.

You help with ANY request: advice, explanations, calculations, \
brainstorming, recipes, learning, analysis, personal questions, \
planning, creative tasks — anything.

You also have built-in features (mention if the request matches):
• Finance: expenses, income, receipts, budgets, analytics, PDF reports
• Email: check inbox, send email, reply
• Calendar: schedule, create events, morning brief
• Tasks: to-dos, reminders, shopping lists
• Tracking: food, drinks, mood, day plan, reflection
• Search: questions, web, comparisons, maps, YouTube
• Writing: messages, posts, translation, proofreading
• Clients: bookings, contacts

Principles:
- Keep it short — the user is in a messenger (3-6 sentences max)
- If you need data you don't have — say exactly what you need
- Don't pretend you can do things you can't
- For greetings — say hi briefly and ask how you can help (1-2 sentences)
- ALWAYS respond in the user's language (detect from their message)
- If the request relates to a feature above, gently suggest it

Formatting: HTML tags for Telegram (<b>, <i>, <code>).
Do NOT use Markdown. Use • (bullet) for lists."""


class GeneralChatSkill:
    name = "general_chat"
    intents = ["general_chat"]
    model = "claude-sonnet-4-6"

    def _get_dosing_prompt(self, suppress: bool) -> str:
        """Return system prompt with or without feature suggestions."""
        if suppress:
            return CHAT_SYSTEM_PROMPT.replace(
                "gently suggest it",
                "do NOT suggest features — the user already knows what you can do",
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
            lang = _detect_greeting_lang(text_raw, context.language)
            return SkillResult(response_text=_time_greeting(context.timezone, lang))

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
                msgs = [{"role": "user", "content": message.text or "Hi"}]
        else:
            sys = system_prompt
            msgs = [{"role": "user", "content": message.text or "Hi"}]

        text = await generate_text(self.model, sys, msgs, max_tokens=1024)
        return SkillResult(response_text=text)

    def get_system_prompt(self, context: SessionContext) -> str:
        return CHAT_SYSTEM_PROMPT


skill = GeneralChatSkill()
