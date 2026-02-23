"""Quick answer skill — factual Q&A using LLM knowledge."""

import logging
from pathlib import Path
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import google_client
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult
from src.skills.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are a knowledgeable assistant answering factual questions.

Rules:
- Lead with the answer. Context comes second.
- For simple facts: 1-3 sentences. For explanations: up to 5.
- For detailed requests (full calendar, schedule, complete list): \
provide ALL the data directly — do NOT summarize or redirect to websites.
- If you're unsure, say "based on my training data" and give your best answer.
- Never make up statistics or cite fake sources.
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- ALWAYS respond in the language of the user's ORIGINAL message (provided below). \
User's preferred language: {language}."""


class QuickAnswerSkill:
    name = "quick_answer"
    intents = ["quick_answer"]
    model = "gemini-3-flash-preview"

    @observe(name="quick_answer")
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
            return SkillResult(response_text="What would you like to know?")

        original_text = message.text or query
        answer = await generate_answer(query, context.language or "en", original_text)
        return SkillResult(response_text=answer)

    def get_system_prompt(self, context: SessionContext) -> str:
        prompts = load_prompt(Path(__file__).parent)
        template = prompts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        return template.format(language=context.language or "en")


async def generate_answer(
    query: str, language: str, original_message: str = ""
) -> str:
    """Generate a factual answer using Gemini Flash."""
    client = google_client()
    system = _DEFAULT_SYSTEM_PROMPT.format(language=language)
    user_msg = original_message or query

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=f"{system}\n\nUser's original message: {user_msg}\nQuestion: {query}",
        )
        return response.text or "I couldn't find an answer. Try rephrasing?"
    except Exception as e:
        logger.warning("Quick answer generation failed: %s", e)
        return "Something went wrong. Try asking again?"


skill = QuickAnswerSkill()
