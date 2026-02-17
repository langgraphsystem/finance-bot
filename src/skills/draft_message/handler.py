"""Draft message skill — composes emails, texts, and messages using Claude Sonnet."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

DRAFT_SYSTEM_PROMPT = """\
You are a writing assistant. The user wants you to draft a message (email, text, note).

Rules:
- Write the draft directly. No preamble like "Here's a draft:".
- Match the formality level to the context (school email = semi-formal, text to friend = casual).
- Keep it concise — say what needs to be said, nothing more.
- Include a subject line if the user mentions "email".
- If the user provides a name, use it for sign-off. Otherwise, skip the signature.
- End with a line break and "Want me to change anything?" (in the user's language).
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- Respond in the user's preferred language: {language}.
- If no preference is set, match the language of their message."""


class DraftMessageSkill:
    name = "draft_message"
    intents = ["draft_message"]
    model = "claude-sonnet-4-5"

    @observe(name="draft_message")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        topic = (
            intent_data.get("writing_topic")
            or intent_data.get("search_topic")
            or message.text
            or ""
        )
        topic = topic.strip()

        if not topic:
            return SkillResult(
                response_text=(
                    "What would you like me to write? Give me the topic and who it's for."
                )
            )

        draft = await generate_draft(topic, context.language or "en")
        return SkillResult(response_text=draft)

    def get_system_prompt(self, context: SessionContext) -> str:
        return DRAFT_SYSTEM_PROMPT.format(language=context.language or "en")


async def generate_draft(topic: str, language: str) -> str:
    """Generate a message draft using Claude Sonnet."""
    client = anthropic_client()
    system = DRAFT_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": topic}],
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            **prompt_data,
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Draft generation failed: %s", e)
        return "I couldn't generate the draft. Try rephrasing?"


skill = DraftMessageSkill()
