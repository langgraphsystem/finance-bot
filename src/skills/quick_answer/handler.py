"""Quick answer skill — factual Q&A using LLM knowledge."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.llm.clients import google_client
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

QUICK_ANSWER_SYSTEM_PROMPT = """\
You are a knowledgeable assistant answering factual questions.

Rules:
- Lead with the answer. Context comes second.
- Be concise: 1-3 sentences for simple facts, up to 5 for explanations.
- If you're unsure, say "based on my training data" and give your best answer.
- Never make up statistics or cite fake sources.
- Use HTML tags for Telegram formatting (<b>bold</b>, <i>italic</i>). No Markdown.
- Respond in the user's preferred language: {language}.
- If no preference is set, match the language of their message."""


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

        answer = await generate_answer(query, context.language or "en")
        return SkillResult(response_text=answer)

    def get_system_prompt(self, context: SessionContext) -> str:
        return QUICK_ANSWER_SYSTEM_PROMPT.format(language=context.language or "en")


async def generate_answer(query: str, language: str) -> str:
    """Generate a factual answer using Gemini Flash."""
    client = google_client()
    system = QUICK_ANSWER_SYSTEM_PROMPT.format(language=language)

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=f"{system}\n\nQuestion: {query}",
        )
        return response.text or "I couldn't find an answer. Try rephrasing?"
    except Exception as e:
        logger.warning("Quick answer generation failed: %s", e)
        return "Something went wrong. Try asking again?"


skill = QuickAnswerSkill()
