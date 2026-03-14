"""Web search skill — search the web using Gemini with Google Search grounding."""

import logging
from typing import Any

from google.genai import types

from src.core.config import settings
from src.core.context import SessionContext
from src.core.llm.clients import google_client
from src.core.observability import observe
from src.core.research.dual_search import dual_search
from src.core.research.signal_detector import detect_signals
from src.gateway.types import IncomingMessage
from src.skills._i18n import register_strings, t
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

WEB_SEARCH_SYSTEM_PROMPT = """\
You are a research assistant with web search access.

Rules:
- Lead with the answer. Supporting details come second.
- Use bullet points for structured information.
- For simple questions: 3-7 lines, be scannable.
- For detailed requests (full calendar, complete list, table, schedule): \
provide ALL the data the user asked for — do NOT summarize or redirect \
to external websites. Present the full information directly.
- If search results are thin, say what you found and suggest a better query.
- Telegram HTML only: <b>bold</b>, <i>italic</i>, <code>code</code>. No Markdown.
- NEVER use <ul>, <li>, <ol> — Telegram does not support them. Use • for bullet points.
- Tone: match the query mood. Fun/casual topics (food, travel, entertainment, lifestyle) \
— add relevant emojis. Serious topics (legal, medical, financial analysis, business) \
— no emojis, professional tone.
- LOCATION PRIORITY: If the user's message explicitly mentions a city, country, or place, \
ALWAYS search for that exact location. Never override an explicitly mentioned location with \
the user's default/profile location.
- ALWAYS respond in the language of the user's ORIGINAL message (provided below). \
User's preferred language: {language}."""

_STRINGS = {
    "en": {"error": "Couldn't complete the search. Try again or rephrase your question?"},
    "ru": {"error": "Не удалось выполнить поиск. Попробуй ещё раз или переформулируй запрос?"},
    "es": {"error": "No pude completar la búsqueda. ¿Intentas de nuevo o reformula tu pregunta?"},
}

FALLBACK_DISCLAIMER = "\n\n<i>Based on my training data — may not reflect current info.</i>"


register_strings("web_search", _STRINGS)


class WebSearchSkill:
    name = "web_search"
    intents = ["web_search"]
    model = "gemini-3.1-flash-lite-preview"

    @observe(name="web_search")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = (
            intent_data.get("search_topic") or intent_data.get("search_query") or message.text or ""
        )
        query = query.strip()

        if not query:
            return SkillResult(response_text="What would you like me to search for?")

        original_text = message.text or query
        language = context.language or "en"
        signals = detect_signals(original_text)
        if signals.should_dual_search and settings.ff_dual_search and settings.xai_api_key:
            answer = await dual_search(
                query, language, original_text,
                gemini_searcher=search_and_answer,
                trace_user_id=str(context.user_id),
            )
        else:
            answer = await search_and_answer(query, language, original_text)
        return SkillResult(response_text=answer)

    def get_system_prompt(self, context: SessionContext) -> str:
        return WEB_SEARCH_SYSTEM_PROMPT.format(language=context.language or "en")


async def search_and_answer(
    query: str, language: str, original_message: str = ""
) -> str:
    """Search the web via Gemini grounding and return a summarized answer."""
    client = google_client()
    system = WEB_SEARCH_SYSTEM_PROMPT.format(language=language)
    user_msg = original_message or query
    prompt = f"{system}\n\nUser's original message: {user_msg}\nSearch query: {query}"

    # Try with Google Search grounding first
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = response.text or ""
        if text:
            return text
    except Exception as e:
        logger.warning("Gemini search grounding failed: %s, falling back to LLM", e)

    # Fallback: Gemini without grounding
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt,
        )
        text = response.text or ""
        if text:
            return text + FALLBACK_DISCLAIMER
    except Exception as e:
        logger.error("Gemini fallback also failed: %s", e)

    lang = language if language in _STRINGS else "en"
    return t(_STRINGS, "error", lang)


skill = WebSearchSkill()
