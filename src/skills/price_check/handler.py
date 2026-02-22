"""Price check skill — check a product price on a website via browser automation."""

import logging
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import generate_text
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
    model = "gpt-5.2"

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

        task = (
            f"Go to the relevant website and find the current price for: {query}. "
            "Return the product name, price, and store URL."
        )

        result = await browser_tool.execute_task(task, max_steps=15, timeout=120)

        if result["success"]:
            raw = result["result"]
            # If Playwright fallback — process raw HTML snippet through LLM
            if result.get("engine") == "playwright":
                return await self._format_playwright_result(query, raw)
            return SkillResult(response_text=raw)

        # Fallback: suggest web search
        return SkillResult(
            response_text=(
                f"I couldn't check that price automatically. "
                f'Want me to search the web for "{query}" pricing instead?'
            )
        )

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
