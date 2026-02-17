"""Translate text skill — translates between languages using Claude Sonnet."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
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


class TranslateTextSkill:
    name = "translate_text"
    intents = ["translate_text"]
    model = "claude-sonnet-4-5"

    @observe(name="translate_text")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        text = (
            intent_data.get("writing_topic")
            or intent_data.get("search_topic")
            or message.text
            or ""
        )
        text = text.strip()

        if not text:
            return SkillResult(response_text="What would you like me to translate?")

        target_language = intent_data.get("target_language") or context.language or "en"

        translation = await generate_translation(text, target_language, context.language or "en")
        return SkillResult(response_text=translation)

    def get_system_prompt(self, context: SessionContext) -> str:
        return TRANSLATE_SYSTEM_PROMPT.format(language=context.language or "en")


async def generate_translation(text: str, target_language: str, system_language: str) -> str:
    """Translate text using Claude Sonnet."""
    client = anthropic_client()
    system = TRANSLATE_SYSTEM_PROMPT.format(language=system_language)
    user_content = TRANSLATE_USER_TEMPLATE.format(
        target_language=target_language,
        text=text,
    )
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            **prompt_data,
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Translation failed: %s", e)
        return "I couldn't translate the text. Try again?"


skill = TranslateTextSkill()
