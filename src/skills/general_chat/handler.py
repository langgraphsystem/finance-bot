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

# Fast-path: affirmations / acknowledgments answered without LLM
_AFFIRMATION_WORDS = frozenset({
    "да", "ок", "ok", "okay", "yes", "yep", "yeah", "yea", "sure",
    "готов", "готова", "ладно", "хорошо", "понял", "поняла", "понятно",
    "ясно", "cool", "nice", "great", "awesome", "got it", "si", "bueno",
    "спасибо", "thanks", "thank you", "спс", "thx", "gracias",
    "круто", "класс", "отлично", "супер", "норм",
})

_AFFIRMATION_EMOJI = frozenset({
    "👍", "👌", "🙌", "✅", "🤝", "💪", "👏", "🔥", "❤️", "😊",
    "😉", "🫡", "✌️", "🫶", "💯",
})

_AFFIRMATION_REPLIES = {
    "en": ["Got it!", "Okay! What's next?", "Sure thing!"],
    "ru": ["Принято!", "Окей! Что дальше?", "Понял!"],
    "es": ["Entendido!", "Ok! Que sigue?", "Listo!"],
}
_THANKS_REPLIES = {
    "en": ["You're welcome!", "Happy to help!", "Anytime!"],
    "ru": ["Пожалуйста!", "Рад помочь!", "Обращайся!"],
    "es": ["De nada!", "Con gusto!", "Cuando quieras!"],
}
_RU_THANKS = frozenset({"спасибо", "спс"})
_EN_THANKS = frozenset({"thanks", "thank you", "thx"})
_ES_THANKS = frozenset({"gracias"})


def _is_greeting(text: str) -> bool:
    """Check if the message is a simple greeting."""
    return text.lower().strip().rstrip("!.?  ") in _GREETING_WORDS


def _is_affirmation(text: str) -> bool:
    """Check if the message is a short affirmation/acknowledgment."""
    cleaned = text.lower().strip().rstrip("!.?  ")
    if cleaned in _AFFIRMATION_WORDS:
        return True
    # Pure emoji messages (1-3 emoji, no other text)
    stripped = text.strip()
    if stripped and all(c in _AFFIRMATION_EMOJI or c in " " for c in stripped):
        return True
    return False


def _is_thanks(text: str) -> bool:
    """Check if the message is a thank-you."""
    cleaned = text.lower().strip().rstrip("!.?  ")
    return cleaned in (_RU_THANKS | _EN_THANKS | _ES_THANKS)


def _affirmation_reply(text: str, context_lang: str | None) -> str:
    """Return a short reply for affirmation or thanks."""
    lang = "en"
    if context_lang and context_lang.startswith("ru"):
        lang = "ru"
    elif context_lang and context_lang.startswith("es"):
        lang = "es"
    # Detect language from text itself
    cleaned = text.lower().strip().rstrip("!.?  ")
    if cleaned in _RU_THANKS or cleaned in {"да", "ок", "готов", "готова", "ладно",
                                              "хорошо", "понял", "поняла", "понятно",
                                              "ясно", "круто", "класс", "отлично",
                                              "супер", "норм"}:
        lang = "ru"
    elif cleaned in _ES_THANKS or cleaned in {"si", "bueno"}:
        lang = "es"

    if _is_thanks(text):
        return random.choice(_THANKS_REPLIES.get(lang, _THANKS_REPLIES["en"]))
    return random.choice(_AFFIRMATION_REPLIES.get(lang, _AFFIRMATION_REPLIES["en"]))


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
• Family: shared tracking with family members via invite code

If user asks about adding family members or invite codes, tell them to type \
"show invite code" or "мой код приглашения" to see their code. \
Family members join by pressing /start and choosing "Join family".

Principles:
- Keep it short — the user is in a messenger (3-6 sentences max)
- For short messages (emoji, "ok", "thanks", single words) — respond in 1 sentence max
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

        # Fast-path: affirmations/emoji/thanks — no LLM needed
        if text_raw and _is_affirmation(text_raw):
            return SkillResult(response_text=_affirmation_reply(text_raw, context.language))

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

        # Dynamic max_tokens: short inputs get shorter responses
        max_tok = 256 if len(text_raw) < 20 else 1024
        text = await generate_text(self.model, sys, msgs, max_tokens=max_tok)
        return SkillResult(response_text=text)

    def get_system_prompt(self, context: SessionContext) -> str:
        return CHAT_SYSTEM_PROMPT


skill = GeneralChatSkill()
