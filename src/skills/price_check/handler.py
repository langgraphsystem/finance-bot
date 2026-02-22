"""Price check skill — check a product price via Google Search, browser fallback."""

import logging
from pathlib import Path
from typing import Any

from google.genai import types

from src.core.context import SessionContext
from src.core.llm.clients import generate_text, google_client
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt
from src.tools.browser import browser_tool

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You check product prices on websites for the user.
Give the price, product name, and store. Be concise.
ALWAYS respond in the same language as the user's message/query."""

_GROUNDING_PROMPT = """\
Find the current price for: {query}

Rules:
- Return: product name, exact price, store name/URL.
- If multiple options exist, show 2-3 best matches.
- Use HTML tags for Telegram (<b>bold</b>, <i>italic</i>). No Markdown.
- ALWAYS respond in {language}."""

_FORMAT_PROMPT = """\
The user asked: "{query}"
Browser returned this raw data:

{raw}

Extract the key information and respond concisely in the same language as the user's query.
Include: product name, price, store name/URL. Use Telegram HTML (<b>, <i>).
If the data is not useful, say you couldn't find the price."""


class PriceCheckSkill:
    name = "price_check"
    intents = ["price_check"]
    model = "gemini-3-flash-preview"

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language or "en")

    @observe(name="price_check")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        query = message.text or ""
        if not query:
            return SkillResult(
                response_text="What product would you like me to check the price for?"
            )

        language = context.language or "en"

        # 1. Fast path: Gemini Google Search Grounding (~2-3s)
        grounding_result = await self._search_price_grounding(query, language)
        if grounding_result:
            return SkillResult(response_text=grounding_result)

        # 2. Slow path: Browser-Use fallback (~60-120s)
        task = (
            f"Find the current price for: {query}. "
            "Return the product name, price, and store URL. "
            "IMPORTANT: If the website blocks your access or shows error pages, "
            "do NOT keep retrying. Search Google instead and return what you find."
        )
        result = await browser_tool.execute_task(task, max_steps=15, timeout=120)

        if result["success"]:
            raw = result["result"]
            if result.get("engine") == "playwright":
                return await self._format_playwright_result(query, raw)
            return SkillResult(response_text=raw)

        return SkillResult(
            response_text=(
                f"I couldn't check that price automatically. "
                f'Want me to search the web for "{query}" pricing instead?'
            )
        )

    async def _search_price_grounding(self, query: str, language: str) -> str | None:
        """Search for price via Gemini Google Search Grounding."""
        client = google_client()
        prompt = _GROUNDING_PROMPT.format(query=query, language=language)

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
            logger.warning("Gemini price grounding failed: %s, falling back to browser", e)

        return None

    async def _format_playwright_result(self, query: str, raw: str) -> SkillResult:
        """Process raw Playwright output through LLM for clean response."""
        try:
            prompt = _FORMAT_PROMPT.format(query=query, raw=raw[:2000])
            answer = await generate_text(
                "gemini-3-flash-preview",
                "You format browser data into concise answers.",
                [{"role": "user", "content": prompt}],
                max_tokens=512,
            )
            return SkillResult(response_text=answer)
        except Exception as e:
            logger.warning("Failed to format playwright result: %s", e)
            return SkillResult(response_text=raw)


skill = PriceCheckSkill()
