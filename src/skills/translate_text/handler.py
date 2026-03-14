"""Translate text skill — translates between languages using Gemini Flash."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

TRANSLATE_SYSTEM_PROMPT = """\
You are a translation assistant. The user wants text translated.

Rules:
- Output ONLY the translated text. No commentary, no "Here's the translation:".
- Preserve the original tone and formality level.
- If the target language isn't specified, translate to: {language}.
- If the source text is already in the target language, say so briefly.
- Preserve formatting (line breaks, bullet points) from the original.
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- For ambiguous words, pick the most common translation in context."""

TRANSLATE_USER_TEMPLATE = """\
Translate the following to {target_language}:

{text}"""

_STRINGS = {
    "en": {
        "ask_text": "What would you like me to translate?",
        "error": "Couldn't translate the text. Try again?",
    },
    "ru": {
        "ask_text": "Что нужно перевести?",
        "error": "Не удалось выполнить перевод. Попробуй ещё раз?",
    },
    "es": {
        "ask_text": "¿Qué quieres que traduzca?",
        "error": "No pude traducir el texto. ¿Intentas de nuevo?",
    },
}
register_strings("translate_text", _STRINGS)


class TranslateTextSkill:
    name = "translate_text"
    intents = ["translate_text"]
    model = "gemini-3.1-flash-lite-preview"

    @observe(name="translate_text")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        text = (
            intent_data.get("writing_topic")
            or intent_data.get("search_topic")
            or message.text
            or ""
        )
        text = text.strip()

        if not text:
            return SkillResult(response_text=t(_STRINGS, "ask_text", lang))

        target_language = intent_data.get("target_language") or context.language or "en"

        translation = await generate_translation(text, target_language, lang)
        return SkillResult(response_text=translation)

    def get_system_prompt(self, context: SessionContext) -> str:
        return TRANSLATE_SYSTEM_PROMPT.format(language=context.language or "en")


async def generate_translation(text: str, target_language: str, system_language: str) -> str:
    """Translate text using Gemini Flash."""
    system = TRANSLATE_SYSTEM_PROMPT.format(language=system_language)
    user_content = TRANSLATE_USER_TEMPLATE.format(
        target_language=target_language,
        text=text,
    )
    messages = [{"role": "user", "content": user_content}]

    try:
        return await generate_text("gemini-3.1-flash-lite-preview", system, messages, max_tokens=1024)
    except Exception as e:
        logger.warning("Translation failed: %s", e)
        lang = system_language if system_language in _STRINGS else "en"
        return t(_STRINGS, "error", lang)


skill = TranslateTextSkill()
