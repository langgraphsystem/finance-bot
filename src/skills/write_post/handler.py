"""Write post skill — creates platform-ready content using Claude Sonnet."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import anthropic_client
from src.core.llm.prompts import PromptAdapter
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

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
- Respond in the user's preferred language: {language}.
- If no preference is set, match the language of their message."""


class WritePostSkill:
    name = "write_post"
    intents = ["write_post"]
    model = "claude-sonnet-4-6"

    @observe(name="write_post")
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
                response_text=("What would you like me to write? Tell me the topic and platform.")
            )

        platform = intent_data.get("target_platform") or ""
        if platform:
            topic = f"[Platform: {platform}] {topic}"

        post = await generate_post(topic, context.language or "en")
        return SkillResult(response_text=post)

    def get_system_prompt(self, context: SessionContext) -> str:
        return WRITE_POST_SYSTEM_PROMPT.format(language=context.language or "en")


async def generate_post(topic: str, language: str) -> str:
    """Generate platform-ready content using Claude Sonnet."""
    client = anthropic_client()
    system = WRITE_POST_SYSTEM_PROMPT.format(language=language)
    prompt_data = PromptAdapter.for_claude(
        system=system,
        messages=[{"role": "user", "content": topic}],
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            **prompt_data,
        )
        return response.content[0].text
    except Exception as e:
        logger.warning("Post generation failed: %s", e)
        return "I couldn't generate the content. Try rephrasing?"


skill = WritePostSkill()
