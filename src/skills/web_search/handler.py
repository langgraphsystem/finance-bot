"""Web search skill — search the web using Gemini with Google Search grounding."""

import logging
from typing import Any

from google.genai import types

from src.core.context import SessionContext
from src.core.llm.clients import google_client
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

WEB_SEARCH_SYSTEM_PROMPT = """\
You are a research assistant with web search access.

Rules:
- Lead with the answer. Supporting details come second.
- Use bullet points for structured information.
- Max 5-7 lines. Be scannable, not verbose.
- If search results are thin, say what you found and suggest a better query.
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- Respond in the user's preferred language: {language}.
- If no preference is set, match the language of their message."""

FALLBACK_DISCLAIMER = "\n\n<i>Based on my training data — may not reflect current info.</i>"


class WebSearchSkill:
    name = "web_search"
    intents = ["web_search"]
    model = "gemini-3-flash-preview"

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

        answer = await search_and_answer(query, context.language or "en")
        return SkillResult(response_text=answer)

    def get_system_prompt(self, context: SessionContext) -> str:
        return WEB_SEARCH_SYSTEM_PROMPT.format(language=context.language or "en")


async def search_and_answer(query: str, language: str) -> str:
    """Search the web via Gemini grounding and return a summarized answer."""
    client = google_client()
    system = WEB_SEARCH_SYSTEM_PROMPT.format(language=language)
    prompt = f"{system}\n\nSearch query: {query}"

    # Try with Google Search grounding first
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
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
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        text = response.text or ""
        if text:
            return text + FALLBACK_DISCLAIMER
    except Exception as e:
        logger.error("Gemini fallback also failed: %s", e)

    return "I couldn't complete the search. Try again or rephrase your question?"


skill = WebSearchSkill()
