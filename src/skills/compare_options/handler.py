"""Compare options skill — structured comparison using Gemini Flash."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

COMPARE_SYSTEM_PROMPT = """\
You are a comparison assistant. The user wants to compare options.

Rules:
- Structure the comparison with clear categories (cost, quality, etc.).
- Use bullet points. One line per point.
- Be balanced and factual. No bias unless the user asks for a recommendation.
- If the user asks "which is better?", give a bottom-line recommendation with reasoning.
- Max 10 lines. Dense and scannable.
- If comparing more than 4 items, ask the user to narrow down to 3-4.
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- NEVER use <ul>, <li>, <ol> — use • for bullet points.
- ALWAYS respond in the language of the user's ORIGINAL message. \
User's preferred language: {language}."""

_STRINGS = {
    "en": {
        "ask_topic": "What would you like me to compare?",
        "error": "Couldn't generate the comparison. Try rephrasing?",
    },
    "ru": {
        "ask_topic": "Что сравниваем?",
        "error": "Не удалось сгенерировать сравнение. Попробуй переформулировать?",
    },
    "es": {
        "ask_topic": "¿Qué quieres que compare?",
        "error": "No pude generar la comparación. ¿Intentas reformularlo?",
    },
}
register_strings("compare_options", _STRINGS)


class CompareOptionsSkill:
    name = "compare_options"
    intents = ["compare_options"]
    model = "gemini-3.1-flash-lite-preview"

    @observe(name="compare_options")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        query = (
            intent_data.get("search_topic") or intent_data.get("search_query") or message.text or ""
        )
        query = query.strip()

        if not query:
            return SkillResult(response_text=t(_STRINGS, "ask_topic", lang))

        original_text = message.text or query
        answer = await generate_comparison(query, lang, original_text)
        return SkillResult(response_text=answer)

    def get_system_prompt(self, context: SessionContext) -> str:
        return COMPARE_SYSTEM_PROMPT.format(language=context.language or "en")


async def generate_comparison(
    query: str, language: str, original_message: str = ""
) -> str:
    """Generate a structured comparison using Gemini Flash."""
    system = COMPARE_SYSTEM_PROMPT.format(language=language)
    user_msg = original_message or query
    user_content = f"Original message: {user_msg}\n\nCompare: {query}"
    messages = [{"role": "user", "content": user_content}]

    try:
        return await generate_text("gemini-3.1-flash-lite-preview", system, messages, max_tokens=1024)
    except Exception as e:
        logger.warning("Gemini comparison failed: %s", e)
        lang = language if language in _STRINGS else "en"
        return t(_STRINGS, "error", lang)


skill = CompareOptionsSkill()
