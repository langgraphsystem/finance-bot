"""Query report skill — generate and send PDF reports."""

import logging
from typing import Any

from src.core.context import SessionContext
from src.core.observability import observe
from src.core.reports import generate_monthly_report
from src.gateway.types import IncomingMessage
from src.skills.base import SkillResult

logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = """Ты помогаешь с генерацией финансовых отчётов."""


class QueryReportSkill:
    name = "query_report"
    intents = ["query_report"]
    model = "claude-sonnet-4-5-20250929"

    @observe(name="query_report")
    async def execute(
        self,
        message: IncomingMessage,
        context: SessionContext,
        intent_data: dict[str, Any],
    ) -> SkillResult:
        """Generate and return a PDF report."""
        try:
            pdf_bytes, filename = await generate_monthly_report(
                family_id=context.family_id,
            )
            return SkillResult(
                response_text="Ваш ежемесячный отчёт готов:",
                document=pdf_bytes,
                document_name=filename,
            )
        except Exception as e:
            logger.error("Report generation failed: %s", e, exc_info=True)
            return SkillResult(
                response_text="Ошибка при генерации отчёта. Попробуйте позже.",
            )

    def get_system_prompt(self, context: SessionContext) -> str:
        return REPORT_SYSTEM_PROMPT


skill = QueryReportSkill()
