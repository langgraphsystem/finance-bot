"""Price check skill — check a product price on a website via browser automation."""

import logging
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt
from src.tools.browser import browser_tool

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You check product prices on websites for the user.
Give the price, product name, and store. Be concise.
Respond in: {language}."""


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

        result = await browser_tool.execute_task(task, max_steps=8, timeout=30)

        if result["success"]:
            return SkillResult(response_text=result["result"])

        # Fallback: suggest web search
        return SkillResult(
            response_text=(
                f"I couldn't check that price automatically. "
                f'Want me to search the web for "{query}" pricing instead?'
            )
        )


skill = PriceCheckSkill()
