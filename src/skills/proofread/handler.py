"""Proofread skill — checks grammar and spelling using Claude Haiku."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

PROOFREAD_SYSTEM_PROMPT = """\
You are a proofreading assistant. The user wants you to check their text for errors.

Rules:
- First, output the corrected text.
- Then list each change with a bullet point: original → corrected (reason).
- If there are no errors, say "Looks good — no changes needed."
- Fix: spelling, grammar, punctuation, capitalization, spacing.
- Do NOT rewrite for style — only fix mechanical errors.
- Do NOT change meaning, tone, or word choice.
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- Respond in the user's preferred language: {language}.
- If no preference is set, match the language of the text being proofread."""


class ProofreadSkill:
    name = "proofread"
    intents = ["proofread"]
    model = "claude-haiku-4-5"

    @observe(name="proofread")
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
            return SkillResult(
                response_text="Send me the text you'd like me to proofread."
            )

        result = await check_text(text, context.language or "en")
        return SkillResult(response_text=result)

    def get_system_prompt(self, context: SessionContext) -> str:
        return PROOFREAD_SYSTEM_PROMPT.format(
            language=context.language or "en"
        )


async def check_text(text: str, language: str) -> str:
    """Proofread text using Claude Haiku."""
    client = anthropic_client()
    system = PROOFREAD_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": f"Proofread this:\n\n{text}"}],
    )

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            **prompt_data,
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Proofreading failed: %s", e)
        return "I couldn't proofread the text. Try again?"


skill = ProofreadSkill()
