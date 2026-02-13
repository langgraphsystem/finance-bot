"""Complex query skill — multi-step financial analysis."""

import logging
from typing import Any

from src.agents.graph_agent import run_complex_query
from src.core.context import SessionContext
from src.core.observability import observe
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

COMPLEX_QUERY_PROMPT = """Ты обрабатываешь сложные аналитические запросы."""


class ComplexQuerySkill:
    name = "complex_query"
    intents = ["complex_query"]
    model = "claude-sonnet-4-5-20250929"

    @observe(name="complex_query")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        try:
            insight = await run_complex_query(
                query=message.text or "",
                family_id=context.family_id,
            )

            # Build response
            response_parts = [insight.summary]
            if insight.recommendations:
                response_parts.append("\n\U0001f4a1 Рекомендации:")
                for rec in insight.recommendations:
                    response_parts.append(f"  \u2022 {rec}")

            return SkillResult(
                response_text="\n".join(response_parts),
            )
        except Exception as e:
            logger.error("Complex query failed: %s", e)
            return SkillResult(
                response_text="Не удалось выполнить анализ. Попробуйте позже.",
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return COMPLEX_QUERY_PROMPT


skill = ComplexQuerySkill()
