"""Write post skill — creates platform-ready content using Claude Sonnet."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

_STRINGS = {
    "en": {
        "ask_topic": "What would you like me to write? Tell me the topic and platform.",
        "error": "I couldn't generate the content. Try rephrasing?",
    },
    "ru": {
        "ask_topic": "О чём написать? Укажи тему и платформу.",
        "error": "Не удалось сгенерировать текст. Попробуй переформулировать?",
    },
    "es": {
        "ask_topic": "¿Sobre qué quieres que escriba? Dime el tema y la plataforma.",
        "error": "No pude generar el contenido. ¿Intentas reformularlo?",
    },
}
register_strings("write_post", _STRINGS)

WRITE_POST_SYSTEM_PROMPT = """\
You are a content writing assistant. The user wants to write a post, review response, \
social media caption, or other platform-specific content.

Rules:
- Write the content directly. No preamble.
- Adapt style to the platform if specified (Google review = professional and empathetic, \
Instagram = casual with line breaks, business response = calm and solution-oriented).
- For review responses: acknowledge the feedback, stay professional, offer resolution.
- For social posts: keep it punchy, add line breaks for readability.
- Max length: appropriate for the platform (Google review ~100 words, social post ~150 words).
- End with "Want me to adjust the tone?" (in the user's language).
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- ALWAYS respond in the same language as the user's message/query."""


class WritePostSkill:
    name = "write_post"
    intents = ["write_post"]
    model = "gemini-3.1-flash-lite-preview"

    @observe(name="write_post")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        lang = context.language or "en"
        topic = (
            intent_data.get("writing_topic")
            or intent_data.get("search_topic")
            or message.text
            or ""
        )
        topic = topic.strip()

        if not topic:
            return SkillResult(
                response_text=t(_STRINGS, "ask_topic", lang)
            )

        platform = intent_data.get("target_platform") or ""
        if platform:
            topic = f"[Platform: {platform}] {topic}"

        post = await generate_post(topic, lang)

        try:
            from src.core.memory.episodic import store_episode

            await store_episode(
                user_id=str(context.user_id),
                family_id=str(context.family_id),
                intent="write_post",
                result_metadata={
                    "topic": topic[:100],
                    "platform": platform or "general",
                },
            )
        except Exception as e:
            logger.debug("Episode storage failed: %s", e)

        return SkillResult(response_text=post)

    def get_system_prompt(self, context: SessionContext) -> str:
        return WRITE_POST_SYSTEM_PROMPT.format(language=context.language or "en")


async def generate_post(topic: str, language: str) -> str:
    """Generate platform-ready content using Gemini Flash."""
    system = WRITE_POST_SYSTEM_PROMPT
    system = f"IMPORTANT: Write ONLY in {language}. Do NOT use any other language.\n\n" + system
    messages = [{"role": "user", "content": topic}]

    try:
        return await generate_text("gemini-3.1-flash-lite-preview", system, messages, max_tokens=1024)
    except Exception as e:
        logger.warning("Post generation failed: %s", e)
        lang = language if language in _STRINGS else "en"
        return t(_STRINGS, "error", lang)


skill = WritePostSkill()
